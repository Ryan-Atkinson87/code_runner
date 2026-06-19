from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config.schema import RepoCommands
from app.engine.implement_loop import (
    ImplementOutcome,
    _build_fix_prompt,
    _build_implement_prompt,
    _commit_wip,
    implement_and_gate,
)
from app.engine.markers import IssueMarker, WaveStep
from app.gates.runner import GateResult, GateRunResult, GateStatus
from app.git.repo import GitRepo
from app.providers.types import (
    SessionOutcome,
    SessionResult,
    UsageReport,
)
from app.renderer.base import RenderedOutput


def _init_repo(tmp_path: Path) -> GitRepo:
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
    return GitRepo(tmp_path)


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
        INSERT INTO runs (project, milestone) VALUES ('test', 'milestone-1');
    """)
    return conn


def _session_result(duration: float = 10.0) -> SessionResult:
    return SessionResult(
        outcome=SessionOutcome.COMPLETED,
        usage=UsageReport(duration_seconds=duration),
    )


def _gate_passed() -> GateRunResult:
    return GateRunResult(
        repo_name="test-repo",
        results=(
            GateResult("test", GateStatus.PASSED, 0, "ok", "", 1.0),
            GateResult("lint", GateStatus.PASSED, 0, "ok", "", 0.5),
            GateResult("typecheck", GateStatus.PASSED, 0, "ok", "", 0.3),
        ),
    )


def _gate_failed() -> GateRunResult:
    return GateRunResult(
        repo_name="test-repo",
        results=(
            GateResult("test", GateStatus.FAILED, 1, "", "test failure", 1.0),
            GateResult("lint", GateStatus.PASSED, 0, "ok", "", 0.5),
            GateResult("typecheck", GateStatus.PASSED, 0, "ok", "", 0.3),
        ),
    )


def _rendered_output() -> RenderedOutput:
    return RenderedOutput(files={"CLAUDE.md": "# test instructions\n"})


class TestBuildImplementPrompt:
    def test_fresh_start(self) -> None:
        prompt = _build_implement_prompt("Fix the bug")
        assert "Implement" in prompt
        assert "Fix the bug" in prompt
        assert "checkpoint" not in prompt.lower()

    def test_continuation(self) -> None:
        prompt = _build_implement_prompt("Fix the bug", is_continuation=True)
        assert "Continue" in prompt
        assert "checkpoint" in prompt.lower()
        assert "Fix the bug" in prompt


class TestBuildFixPrompt:
    def test_includes_gate_failures(self) -> None:
        gate = _gate_failed()
        prompt = _build_fix_prompt("issue body", gate)
        assert "gate failures" in prompt.lower()
        assert "test failure" in prompt
        assert "issue body" in prompt

    def test_includes_only_failed_gates(self) -> None:
        gate = _gate_failed()
        prompt = _build_fix_prompt("body", gate)
        assert "test" in prompt.lower()
        assert "exit code 1" in prompt


class TestCommitWip:
    def test_commits_dirty_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (tmp_path / "new.py").write_text("# new")
        sha = _commit_wip(repo, 42)
        assert sha is not None
        assert not repo.is_dirty()

    def test_returns_none_for_clean_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        sha = _commit_wip(repo, 42)
        assert sha is None

    def test_commit_message_includes_issue(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        (tmp_path / "wip.py").write_text("# wip")
        _commit_wip(repo, 99)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert "#99" in result.stdout


class TestImplementAndGate:
    @pytest.mark.asyncio
    async def test_gates_pass_first_try(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_passed()):
            result = await implement_and_gate(
                issue_number=1,
                issue_body="Fix the bug",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
            )

        assert result.outcome == ImplementOutcome.GATES_PASSED
        assert result.gate_result is not None
        assert result.gate_result.all_passed
        assert len(result.sessions) == 1
        assert result.blocker is None
        adapter.run_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_gate_fail_then_fix(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        gate_results = [_gate_failed(), _gate_passed()]
        with patch("app.engine.implement_loop.run_gates", side_effect=gate_results):
            result = await implement_and_gate(
                issue_number=1,
                issue_body="Fix the bug",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
            )

        assert result.outcome == ImplementOutcome.GATES_PASSED
        assert len(result.sessions) == 2
        assert adapter.run_session.call_count == 2

    @pytest.mark.asyncio
    async def test_exceed_fix_bound(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_failed()):
            result = await implement_and_gate(
                issue_number=1,
                issue_body="Fix the bug",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="false"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
                test_fix_attempts=3,
            )

        assert result.outcome == ImplementOutcome.PARKED_FIX_BOUND
        assert result.blocker is not None
        assert "3 fix attempts" in result.blocker.reason
        assert len(result.sessions) == 3
        assert result.blocker.last_gate_result is not None

    @pytest.mark.asyncio
    async def test_checkpoint_commits_and_resumes(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)

        call_count = 0

        async def mock_session(**kwargs: object) -> SessionResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                (tmp_path / "wip.py").write_text("# work in progress")
                return _session_result(duration=2000.0)
            return _session_result(duration=10.0)

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(side_effect=mock_session)

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_passed()):
            result = await implement_and_gate(
                issue_number=1,
                issue_body="Big task",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
                checkpoint_timeout=1800.0,
            )

        assert result.outcome == ImplementOutcome.GATES_PASSED
        assert len(result.sessions) == 2
        marker = marker_store.read(1, 1)
        assert marker is not None

    @pytest.mark.asyncio
    async def test_checkpoint_never_triggers_discard(self, tmp_path: Path) -> None:
        """Checkpoint commits WIP, so the repo is clean after — no discard path."""
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)

        call_count = 0

        async def mock_session(**kwargs: object) -> SessionResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                (tmp_path / "work.py").write_text("# modified")
                return _session_result(duration=2000.0)
            return _session_result(duration=10.0)

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(side_effect=mock_session)

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_passed()):
            result = await implement_and_gate(
                issue_number=1,
                issue_body="Task",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
                checkpoint_timeout=1800.0,
            )

        assert result.outcome == ImplementOutcome.GATES_PASSED

    @pytest.mark.asyncio
    async def test_stuck_agent_parks_after_max_checkpoints(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)

        call_count = 0

        async def mock_session(**kwargs: object) -> SessionResult:
            nonlocal call_count
            call_count += 1
            (tmp_path / f"file{call_count}.py").write_text(f"# session {call_count}")
            return _session_result(duration=2000.0)

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(side_effect=mock_session)

        result = await implement_and_gate(
            issue_number=1,
            issue_body="Hard task",
            repo=repo,
            repo_name="test-repo",
            repo_path=tmp_path,
            adapter=adapter,
            gate_commands=RepoCommands(test="true"),
            rendered_output=_rendered_output(),
            marker_store=marker_store,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            checkpoint_timeout=1800.0,
            max_checkpoints=3,
        )

        assert result.outcome == ImplementOutcome.PARKED_STUCK
        assert result.blocker is not None
        assert "3 checkpoints" in result.blocker.reason
        assert len(result.sessions) == 3

    @pytest.mark.asyncio
    async def test_markers_updated_at_boundaries(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_passed()):
            await implement_and_gate(
                issue_number=5,
                issue_body="Task",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
            )

        marker = marker_store.read(1, 5)
        assert marker is not None
        assert marker[0] == WaveStep.TEST_GATE

    @pytest.mark.asyncio
    async def test_writes_rendered_output(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        rendered = RenderedOutput(
            files={"CLAUDE.md": "# instructions\n", ".claude/skills/test/SKILL.md": "skill\n"}
        )

        with patch("app.engine.implement_loop.run_gates", return_value=_gate_passed()):
            await implement_and_gate(
                issue_number=1,
                issue_body="Task",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=rendered,
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
            )

        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude/skills/test/SKILL.md").exists()

    @pytest.mark.asyncio
    async def test_fix_prompt_sent_on_gate_failure(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_result())

        gate_results = [_gate_failed(), _gate_passed()]
        with patch("app.engine.implement_loop.run_gates", side_effect=gate_results):
            await implement_and_gate(
                issue_number=1,
                issue_body="Fix the bug",
                repo=repo,
                repo_name="test-repo",
                repo_path=tmp_path,
                adapter=adapter,
                gate_commands=RepoCommands(test="true"),
                rendered_output=_rendered_output(),
                marker_store=marker_store,
                run_id=1,
                model="claude-sonnet-4-6",
                allowed_tools=["bash"],
            )

        calls = adapter.run_session.call_args_list
        first_prompt = calls[0].kwargs.get("prompt", calls[0][1] if len(calls[0]) > 1 else "")
        second_prompt = calls[1].kwargs.get("prompt", calls[1][1] if len(calls[1]) > 1 else "")
        assert "Implement" in first_prompt
        assert "gate failures" in second_prompt.lower()
