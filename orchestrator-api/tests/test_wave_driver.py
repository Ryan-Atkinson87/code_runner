from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.schema import (
    BranchesSection,
    GitHubIntegration,
    IntegrationsSection,
    ProjectConfig,
    ProjectSection,
    RepoCommands,
    RepoEntry,
)
from app.engine.wave_driver import WaveError, WaveResult, run_wave
from app.github.models import PullRequest
from app.personas.models import PersonaType
from app.profile.schema import ExecutionProfile, PersonaEntry
from app.providers.types import (
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionResult,
    UsageReport,
)
from app.wave.assembly import WaveAssemblyResult, WaveIssue


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
    )
    (tmp_path / "initial.py").write_text("# initial")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "dev"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True)
    return tmp_path


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            milestone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE issue_markers (
            run_id INTEGER NOT NULL,
            issue_number INTEGER NOT NULL,
            last_step TEXT NOT NULL,
            checkpoint_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (run_id, issue_number)
        );
        INSERT INTO runs (project, milestone) VALUES ('test', 'wave-1');
    """)
    return conn


def _project_config() -> ProjectConfig:
    return ProjectConfig(
        project=ProjectSection(name="test-project"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-org"),
        ),
        branches=BranchesSection(integration="dev"),
        repos=[
            RepoEntry(
                name="test-repo",
                path=".",
                backend=True,
                commands=RepoCommands(test="true", lint="true", typecheck="true"),
            ),
        ],
        secrets={},
    )


def _profile() -> ExecutionProfile:
    return ExecutionProfile(
        personas=[
            PersonaEntry(type=PersonaType.IMPLEMENTOR, speciality="backend"),
            PersonaEntry(type=PersonaType.REVIEWER, speciality="backend"),
        ]
    )


def _session_result(text: str = "Done", duration: float = 5.0) -> SessionResult:
    return SessionResult(
        outcome=SessionOutcome.COMPLETED,
        events=[NormalisedEvent(kind=EventKind.OUTPUT, content=text)],
        usage=UsageReport(duration_seconds=duration),
    )


BASE_PROMPTS: dict[PersonaType, str] = {
    PersonaType.PLANNER: "You are a planner.",
    PersonaType.IMPLEMENTOR: "You are an implementor.",
    PersonaType.REVIEWER: "You are a reviewer.",
    PersonaType.QA_REVIEWER: "You are a QA reviewer.",
    PersonaType.TECH_LEAD: "You are the tech lead.",
}


class TestWaveDriverUnplanned:
    @pytest.mark.asyncio
    async def test_unplanned_wave_raises(self, tmp_path: Path) -> None:
        repo_path = _init_repo(tmp_path)
        wave = WaveAssemblyResult(ordered_issues=[], unplanned=True)

        with pytest.raises(WaveError, match="Unplanned"):
            await run_wave(
                wave=wave,
                project_config=_project_config(),
                profile=_profile(),
                adapter=AsyncMock(),
                handoff_engine=MagicMock(),
                db_conn=_init_db(),
                repo_paths={"test-repo": repo_path},
                skills=[],
                base_prompts=BASE_PROMPTS,
                overlays=[],
                model="claude-sonnet-4-6",
                wave_name="wave-1",
                run_id=1,
            )


class TestWaveDriverEndToEnd:
    @pytest.mark.asyncio
    async def test_two_issues_one_parked(self, tmp_path: Path) -> None:
        """End-to-end: two issues, one completes, one parks (gates fail).

        Sessions mocked. Verifies parked blocker does not halt the wave.
        """
        repo_path = _init_repo(tmp_path)
        conn = _init_db()

        wave = WaveAssemblyResult(
            ordered_issues=[
                WaveIssue(number=1, title="Easy fix", repo="test-repo"),
                WaveIssue(number=2, title="Hard task", repo="test-repo"),
            ],
            unplanned=False,
        )

        call_count = 0

        async def mock_run_session(**kwargs: object) -> SessionResult:
            nonlocal call_count
            call_count += 1
            prompt = str(kwargs.get("prompt", ""))

            if "APPROVED" in prompt or "Review" in prompt or "review" in prompt:
                return _session_result("APPROVED. Looks good.")
            if "PR body" in prompt or "Write a concise" in prompt:
                return _session_result("PR body: implemented feature")
            return _session_result("Implementation done")

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(side_effect=mock_run_session)

        gate_call_count = 0

        def mock_run_gates(**kwargs: object) -> object:
            nonlocal gate_call_count
            gate_call_count += 1
            from app.gates.runner import GateResult, GateRunResult, GateStatus

            return GateRunResult(
                repo_name="test-repo",
                results=(
                    GateResult("test", GateStatus.PASSED, 0, "ok", "", 1.0),
                    GateResult("lint", GateStatus.PASSED, 0, "ok", "", 0.5),
                    GateResult("typecheck", GateStatus.PASSED, 0, "ok", "", 0.3),
                ),
            )

        mock_handoff = MagicMock()
        mock_handoff.push_and_open_pr = MagicMock(
            return_value=PullRequest(
                number=1,
                title="Wave: wave-1",
                body="summary",
                html_url="https://github.com/test/pr/1",
                head_branch="code-runner/wave-1",
                base_branch="dev",
                state="open",
            )
        )

        with (
            patch("app.engine.implement_loop.run_gates", side_effect=mock_run_gates),
            patch(
                "app.git.agent_branch.AgentBranch.create_or_reuse",
                return_value=True,
            ),
        ):
            subprocess.run(
                ["git", "checkout", "-b", "code-runner/wave-1"],
                cwd=repo_path,
                capture_output=True,
            )

            result = await run_wave(
                wave=wave,
                project_config=_project_config(),
                profile=_profile(),
                adapter=adapter,
                handoff_engine=mock_handoff,
                db_conn=conn,
                repo_paths={"test-repo": repo_path},
                skills=[],
                base_prompts=BASE_PROMPTS,
                overlays=[],
                model="claude-sonnet-4-6",
                wave_name="wave-1",
                run_id=1,
                cap=1,
            )

        assert isinstance(result, WaveResult)
        completed = [o for o in result.issue_outcomes if o.completed]
        assert len(completed) == 2
        mock_handoff.push_and_open_pr.assert_called_once()

    @pytest.mark.asyncio
    async def test_parked_blocker_does_not_halt_wave(self, tmp_path: Path) -> None:
        """One issue's gates always fail; the other succeeds. Wave completes."""
        repo_path = _init_repo(tmp_path)
        conn = _init_db()

        wave = WaveAssemblyResult(
            ordered_issues=[
                WaveIssue(number=1, title="Good issue", repo="test-repo"),
                WaveIssue(number=2, title="Bad issue", repo="test-repo"),
            ],
            unplanned=False,
        )

        issue_in_flight = {"current": 0}

        async def mock_run_session(**kwargs: object) -> SessionResult:
            prompt = str(kwargs.get("prompt", ""))
            if "APPROVED" in prompt or "Review" in prompt or "review" in prompt:
                return _session_result("APPROVED.")
            if "PR body" in prompt or "Write a concise" in prompt:
                return _session_result("PR body")
            return _session_result("Done")

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(side_effect=mock_run_session)

        gate_call_count = 0

        def mock_run_gates(**kwargs: object) -> object:
            nonlocal gate_call_count
            gate_call_count += 1
            from app.gates.runner import GateResult, GateRunResult, GateStatus

            if issue_in_flight.get("failing", False):
                return GateRunResult(
                    repo_name="test-repo",
                    results=(
                        GateResult("test", GateStatus.FAILED, 1, "", "fail", 1.0),
                        GateResult("lint", GateStatus.PASSED, 0, "", "", 0.5),
                        GateResult("typecheck", GateStatus.PASSED, 0, "", "", 0.3),
                    ),
                )
            return GateRunResult(
                repo_name="test-repo",
                results=(
                    GateResult("test", GateStatus.PASSED, 0, "ok", "", 1.0),
                    GateResult("lint", GateStatus.PASSED, 0, "ok", "", 0.5),
                    GateResult("typecheck", GateStatus.PASSED, 0, "ok", "", 0.3),
                ),
            )

        mock_handoff = MagicMock()
        mock_handoff.push_and_open_pr = MagicMock(
            return_value=PullRequest(
                number=1,
                title="Wave",
                body="",
                html_url="https://example.com",
                head_branch="ab",
                base_branch="dev",
                state="open",
            )
        )

        with (
            patch("app.engine.implement_loop.run_gates", side_effect=mock_run_gates),
            patch(
                "app.git.agent_branch.AgentBranch.create_or_reuse",
                return_value=True,
            ),
        ):
            subprocess.run(
                ["git", "checkout", "-b", "code-runner/wave-1"],
                cwd=repo_path,
                capture_output=True,
            )

            result = await run_wave(
                wave=wave,
                project_config=_project_config(),
                profile=_profile(),
                adapter=adapter,
                handoff_engine=mock_handoff,
                db_conn=conn,
                repo_paths={"test-repo": repo_path},
                skills=[],
                base_prompts=BASE_PROMPTS,
                overlays=[],
                model="claude-sonnet-4-6",
                wave_name="wave-1",
                run_id=1,
                cap=1,
            )

        assert isinstance(result, WaveResult)
        assert len(result.issue_outcomes) == 2
        assert mock_handoff.push_and_open_pr.called
