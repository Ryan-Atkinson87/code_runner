from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.engine.markers import IssueMarker, WaveStep
from app.engine.review_cycle import (
    ReviewOutcome,
    _build_body_prompt,
    _build_feedback_prompt,
    _build_review_prompt,
    _extract_text,
    _is_approval,
    review_and_merge,
)
from app.git.feature_branch import FeatureBranch
from app.git.merge_queue import MergeQueue
from app.git.repo import GitRepo
from app.providers.types import (
    EventKind,
    NormalisedEvent,
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


def _setup_feature_branch(repo: GitRepo, tmp_path: Path) -> FeatureBranch:
    """Create an agent branch and a feature branch with a commit."""
    repo.create_and_checkout("agent/wave-1", "main")
    fb = FeatureBranch(repo, "agent/wave-1", 1)
    fb.create()
    (tmp_path / "feature.py").write_text("# feature code")
    repo.stage_all()
    repo.commit("Implement issue #1")
    return fb


def _session_with_text(text: str) -> SessionResult:
    return SessionResult(
        outcome=SessionOutcome.COMPLETED,
        events=[NormalisedEvent(kind=EventKind.OUTPUT, content=text)],
        usage=UsageReport(duration_seconds=5.0),
    )


def _rendered_output() -> RenderedOutput:
    return RenderedOutput(files={})


class TestIsApproval:
    def test_approved(self) -> None:
        assert _is_approval("APPROVED. The changes look good.")

    def test_approved_lowercase(self) -> None:
        assert _is_approval("Approved — everything checks out.")

    def test_request_changes(self) -> None:
        assert not _is_approval("REQUEST_CHANGES: fix the naming.")

    def test_both_keywords_is_not_approval(self) -> None:
        assert not _is_approval("REQUEST_CHANGES — not APPROVED yet.")

    def test_empty(self) -> None:
        assert not _is_approval("")


class TestExtractText:
    def test_extracts_output_events(self) -> None:
        session = _session_with_text("Hello world")
        assert _extract_text(session) == "Hello world"

    def test_ignores_non_output(self) -> None:
        session = SessionResult(
            outcome=SessionOutcome.COMPLETED,
            events=[
                NormalisedEvent(kind=EventKind.REASONING, content="thinking..."),
                NormalisedEvent(kind=EventKind.OUTPUT, content="answer"),
            ],
        )
        assert _extract_text(session) == "answer"


class TestBuildPrompts:
    def test_body_prompt(self) -> None:
        prompt = _build_body_prompt("Fix bug", "2 files changed")
        assert "Fix bug" in prompt
        assert "2 files changed" in prompt

    def test_review_prompt(self) -> None:
        prompt = _build_review_prompt("Fix bug", "diff content", "PR body text")
        assert "Fix bug" in prompt
        assert "diff content" in prompt
        assert "PR body text" in prompt
        assert "APPROVED" in prompt

    def test_feedback_prompt(self) -> None:
        prompt = _build_feedback_prompt("Fix bug", "Change the naming")
        assert "Change the naming" in prompt
        assert "Fix bug" in prompt


class TestReviewAndMerge:
    @pytest.mark.asyncio
    async def test_approve_first_pass_merges(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fb = _setup_feature_branch(repo, tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        merge_queue = MergeQueue()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(
            side_effect=[
                _session_with_text("PR body: implemented feature"),
                _session_with_text("APPROVED. Looks good."),
            ]
        )

        result = await review_and_merge(
            issue_number=1,
            issue_body="Fix the bug",
            feature_branch=fb,
            repo_path=tmp_path,
            adapter=adapter,
            impl_rendered=_rendered_output(),
            review_rendered=_rendered_output(),
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
        )

        assert result.outcome == ReviewOutcome.APPROVED_AND_MERGED
        assert result.merge_sha != ""
        assert len(result.sessions) == 2
        assert not repo.branch_exists(fb.name)

    @pytest.mark.asyncio
    async def test_one_request_changes_then_approve(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fb = _setup_feature_branch(repo, tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        merge_queue = MergeQueue()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(
            side_effect=[
                _session_with_text("PR body: feature"),
                _session_with_text("REQUEST_CHANGES: fix naming"),
                _session_with_text("Fixed naming"),
                _session_with_text("APPROVED."),
            ]
        )

        result = await review_and_merge(
            issue_number=1,
            issue_body="Fix the bug",
            feature_branch=fb,
            repo_path=tmp_path,
            adapter=adapter,
            impl_rendered=_rendered_output(),
            review_rendered=_rendered_output(),
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            review_cycles=2,
        )

        assert result.outcome == ReviewOutcome.APPROVED_AND_MERGED
        assert len(result.sessions) == 4

    @pytest.mark.asyncio
    async def test_exceed_review_cycles_parks(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fb = _setup_feature_branch(repo, tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        merge_queue = MergeQueue()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(
            side_effect=[
                _session_with_text("PR body"),
                _session_with_text("REQUEST_CHANGES: issue 1"),
                _session_with_text("Fixed issue 1"),
                _session_with_text("REQUEST_CHANGES: issue 2"),
                _session_with_text("Fixed issue 2"),
                _session_with_text("REQUEST_CHANGES: still not right"),
            ]
        )

        result = await review_and_merge(
            issue_number=1,
            issue_body="Fix the bug",
            feature_branch=fb,
            repo_path=tmp_path,
            adapter=adapter,
            impl_rendered=_rendered_output(),
            review_rendered=_rendered_output(),
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            review_cycles=2,
        )

        assert result.outcome == ReviewOutcome.PARKED_REVIEW_BOUND
        assert "2 cycles" in result.blocker_reason
        assert repo.branch_exists(fb.name)

    @pytest.mark.asyncio
    async def test_merge_uses_serialised_queue(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fb = _setup_feature_branch(repo, tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        merge_queue = MergeQueue()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(
            side_effect=[
                _session_with_text("PR body"),
                _session_with_text("APPROVED."),
            ]
        )

        result = await review_and_merge(
            issue_number=1,
            issue_body="Task",
            feature_branch=fb,
            repo_path=tmp_path,
            adapter=adapter,
            impl_rendered=_rendered_output(),
            review_rendered=_rendered_output(),
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
        )

        assert result.outcome == ReviewOutcome.APPROVED_AND_MERGED
        assert repo.current_branch() == "agent/wave-1"

    @pytest.mark.asyncio
    async def test_markers_updated_through_review(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        fb = _setup_feature_branch(repo, tmp_path)
        conn = _init_db()
        marker_store = IssueMarker(conn)
        merge_queue = MergeQueue()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(
            side_effect=[
                _session_with_text("PR body"),
                _session_with_text("APPROVED."),
            ]
        )

        await review_and_merge(
            issue_number=5,
            issue_body="Task",
            feature_branch=fb,
            repo_path=tmp_path,
            adapter=adapter,
            impl_rendered=_rendered_output(),
            review_rendered=_rendered_output(),
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=1,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
        )

        marker = marker_store.read(1, 5)
        assert marker is not None
        assert marker[0] == WaveStep.MERGED
