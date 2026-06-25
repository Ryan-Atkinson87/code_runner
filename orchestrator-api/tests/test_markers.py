from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.db.store import StateStore
from app.engine.markers import (
    IssueMarker,
    RecoveryAction,
    WaveStep,
    recovery_action_for,
)
from app.engine.recovery import evaluate_recovery
from app.git.repo import GitRepo


@pytest.fixture()
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "test.db")
    s.open()
    yield s  # type: ignore[misc]
    s.close()


@pytest.fixture()
def marker_store(store: StateStore) -> IssueMarker:
    return IssueMarker(store.conn)


@pytest.fixture()
def run_id(store: StateStore) -> int:
    store.conn.execute(
        "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
        ("test-project", "phase-3", "running"),
    )
    store.conn.commit()
    row = store.conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


def _init_repo(path: Path) -> GitRepo:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, capture_output=True, check=True,
    )
    (path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path, capture_output=True, check=True,
    )
    return GitRepo(path)


class TestMarkerWriteRead:
    def test_write_and_read(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(run_id, 42, WaveStep.TEST_GATE)
        result = marker_store.read(run_id, 42)
        assert result is not None
        step, count = result
        assert step == WaveStep.TEST_GATE
        assert count == 0

    def test_read_missing_returns_none(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        assert marker_store.read(run_id, 999) is None

    def test_write_updates_existing(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(run_id, 10, WaveStep.BRANCH_CREATED)
        marker_store.write(run_id, 10, WaveStep.IMPLEMENTING)
        result = marker_store.read(run_id, 10)
        assert result is not None
        assert result[0] == WaveStep.IMPLEMENTING

    def test_read_all(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(run_id, 1, WaveStep.DEPENDENCY_CHECK)
        marker_store.write(run_id, 2, WaveStep.TEST_GATE)
        all_markers = marker_store.read_all(run_id)
        assert len(all_markers) == 2
        assert all_markers[1][0] == WaveStep.DEPENDENCY_CHECK
        assert all_markers[2][0] == WaveStep.TEST_GATE

    def test_clear(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(run_id, 5, WaveStep.MERGED)
        marker_store.clear(run_id, 5)
        assert marker_store.read(run_id, 5) is None

    def test_checkpoint_count_explicit(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(
            run_id, 7, WaveStep.IMPLEMENTING, checkpoint_count=2,
        )
        result = marker_store.read(run_id, 7)
        assert result is not None
        assert result[1] == 2

    def test_increment_checkpoint(
        self, marker_store: IssueMarker, run_id: int
    ) -> None:
        marker_store.write(run_id, 8, WaveStep.IMPLEMENTING)
        new_count = marker_store.increment_checkpoint(run_id, 8)
        assert new_count == 1
        new_count = marker_store.increment_checkpoint(run_id, 8)
        assert new_count == 2


class TestRecoveryActionFor:
    def test_implementing_resets(self) -> None:
        assert recovery_action_for(WaveStep.IMPLEMENTING) == RecoveryAction.RESET

    def test_test_gate_resumes(self) -> None:
        assert recovery_action_for(WaveStep.TEST_GATE) == RecoveryAction.RESUME

    def test_dependency_check_resumes(self) -> None:
        assert recovery_action_for(WaveStep.DEPENDENCY_CHECK) == RecoveryAction.RESUME

    def test_branch_created_resumes(self) -> None:
        assert recovery_action_for(WaveStep.BRANCH_CREATED) == RecoveryAction.RESUME

    def test_review_resumes(self) -> None:
        assert recovery_action_for(WaveStep.REVIEW) == RecoveryAction.RESUME

    def test_merged_resumes(self) -> None:
        assert recovery_action_for(WaveStep.MERGED) == RecoveryAction.RESUME

    def test_synced_resumes(self) -> None:
        assert recovery_action_for(WaveStep.SYNCED) == RecoveryAction.RESUME


class TestEvaluateRecovery:
    def test_no_branch_no_marker_resumes(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        decision = evaluate_recovery(
            marker_store, repo, run_id, 42,
            "feature/issue-42", "main",
        )
        assert decision.action == RecoveryAction.RESUME
        assert decision.marker_step is None

    def test_resume_after_test_gate(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        repo.create_and_checkout("agent-branch", "main")
        repo.create_and_checkout("feature/issue-10", "agent-branch")
        (repo.path / "code.py").write_text("print('hello')")
        repo.stage_all()
        repo.commit("implement feature")

        marker_store.write(run_id, 10, WaveStep.TEST_GATE)

        decision = evaluate_recovery(
            marker_store, repo, run_id, 10,
            "feature/issue-10", "agent-branch",
        )
        assert decision.action == RecoveryAction.RESUME
        assert decision.marker_step == WaveStep.TEST_GATE

    def test_reset_after_implementing(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        repo.create_and_checkout("agent-branch", "main")
        repo.create_and_checkout("feature/issue-10", "agent-branch")
        (repo.path / "code.py").write_text("partial")
        repo.stage_all()
        repo.commit("partial work")

        marker_store.write(run_id, 10, WaveStep.IMPLEMENTING)

        decision = evaluate_recovery(
            marker_store, repo, run_id, 10,
            "feature/issue-10", "agent-branch",
        )
        assert decision.action == RecoveryAction.RESET
        assert decision.marker_step == WaveStep.IMPLEMENTING

    def test_marker_contradicts_git_defers_to_git(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        """Marker says merged, but branch doesn't exist — git wins."""
        repo = _init_repo(tmp_path / "repo")
        marker_store.write(run_id, 99, WaveStep.MERGED)

        decision = evaluate_recovery(
            marker_store, repo, run_id, 99,
            "feature/issue-99", "main",
        )
        assert decision.action == RecoveryAction.RESUME
        reason = decision.reason.lower()
        assert "fresh start" in reason or "no feature branch" in reason

    def test_commits_no_marker_resets(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        repo.create_and_checkout("agent-branch", "main")
        repo.create_and_checkout("feature/issue-5", "agent-branch")
        (repo.path / "file.py").write_text("code")
        repo.stage_all()
        repo.commit("work")

        decision = evaluate_recovery(
            marker_store, repo, run_id, 5,
            "feature/issue-5", "agent-branch",
        )
        assert decision.action == RecoveryAction.RESET
        assert "no marker" in decision.reason.lower()

    def test_branch_no_commits_resumes(
        self, marker_store: IssueMarker, tmp_path: Path, run_id: int
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        repo.create_and_checkout("agent-branch", "main")
        repo.create_branch("feature/issue-3", "agent-branch")
        repo.checkout("main")

        decision = evaluate_recovery(
            marker_store, repo, run_id, 3,
            "feature/issue-3", "agent-branch",
        )
        assert decision.action == RecoveryAction.RESUME
        assert "no commits" in decision.reason.lower()


class TestMigration:
    def test_issue_markers_table_created(self, store: StateStore) -> None:
        tables = {
            row[0]
            for row in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "issue_markers" in tables

    def test_migration_version_latest(self, store: StateStore) -> None:
        assert store.current_version() == 6


class TestWaveStep:
    def test_all_steps_defined(self) -> None:
        assert len(WaveStep) == 9

    def test_step_values(self) -> None:
        expected = {
            "dependency_check", "branch_created", "implementing",
            "test_gate", "contract_verify", "internal_pr",
            "review", "merged", "synced",
        }
        assert {s.value for s in WaveStep} == expected
