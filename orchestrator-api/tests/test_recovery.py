from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git.recovery import BranchRecovery, BranchState
from app.git.repo import GitRepo


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def agent_repo(tmp_path: Path) -> tuple[GitRepo, str]:
    """A local repo with an agent branch checked out."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _run_git(repo_dir, "init")
    _run_git(repo_dir, "config", "user.email", "test@test.com")
    _run_git(repo_dir, "config", "user.name", "Test")

    (repo_dir / "README.md").write_text("# Project\n")
    _run_git(repo_dir, "add", ".")
    _run_git(repo_dir, "commit", "-m", "initial")

    agent_branch = "code-runner/foundations"
    _run_git(repo_dir, "checkout", "-b", agent_branch)

    return GitRepo(repo_dir), agent_branch


class TestClassifyAbsent:
    def test_no_branch_returns_absent(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        recovery = BranchRecovery(repo, agent)

        result = recovery.classify(99)

        assert result.state == BranchState.ABSENT
        assert result.issue_number == 99
        assert result.branch_name == "feature/issue-99"
        assert result.commits_ahead == 0


class TestClassifyEmpty:
    def test_branch_with_no_commits_returns_empty(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-1", agent)
        repo.checkout(agent)
        recovery = BranchRecovery(repo, agent)

        result = recovery.classify(1)

        assert result.state == BranchState.EMPTY
        assert result.commits_ahead == 0


class TestClassifyDirty:
    def test_dirty_working_tree_returns_dirty(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-5", agent)
        (repo.path / "wip.py").write_text("partial work\n")

        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(5)

        assert result.state == BranchState.DIRTY

    def test_dirty_on_different_branch_returns_commits_or_empty(
        self, agent_repo: tuple[GitRepo, str]
    ) -> None:
        """Dirty state only applies when the feature branch is checked out."""
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-5", agent)
        repo.checkout(agent)
        (repo.path / "unrelated.txt").write_text("dirty on agent\n")

        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(5)

        assert result.state == BranchState.EMPTY

    def test_dirty_with_staged_changes(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-5", agent)
        (repo.path / "staged.py").write_text("staged\n")
        repo.stage("staged.py")

        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(5)

        assert result.state == BranchState.DIRTY


class TestClassifyCommitsOnly:
    def test_commits_not_merged_returns_commits_only(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-10", agent)
        (repo.path / "impl.py").write_text("implementation\n")
        repo.stage_all()
        repo.commit("implement issue 10")

        repo.checkout(agent)
        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(10)

        assert result.state == BranchState.COMMITS_ONLY
        assert result.commits_ahead == 1

    def test_multiple_commits_counted(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-10", agent)

        (repo.path / "a.py").write_text("a\n")
        repo.stage_all()
        repo.commit("first")

        (repo.path / "b.py").write_text("b\n")
        repo.stage_all()
        repo.commit("second")

        repo.checkout(agent)
        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(10)

        assert result.state == BranchState.COMMITS_ONLY
        assert result.commits_ahead == 2


class TestClassifyMerged:
    def test_merged_branch_returns_merged(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-7", agent)
        (repo.path / "done.py").write_text("done\n")
        repo.stage_all()
        repo.commit("implement issue 7")

        repo.checkout(agent)
        repo.merge("feature/issue-7", message="Merge issue #7")

        recovery = BranchRecovery(repo, agent)
        result = recovery.classify(7)

        assert result.state == BranchState.MERGED

    def test_merged_is_idempotent(self, agent_repo: tuple[GitRepo, str]) -> None:
        """Classifying a merged branch multiple times always returns MERGED."""
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-7", agent)
        (repo.path / "done.py").write_text("done\n")
        repo.stage_all()
        repo.commit("implement issue 7")

        repo.checkout(agent)
        repo.merge("feature/issue-7", message="Merge issue #7")

        recovery = BranchRecovery(repo, agent)
        assert recovery.classify(7).state == BranchState.MERGED
        assert recovery.classify(7).state == BranchState.MERGED


class TestClassifyAll:
    def test_classifies_multiple_issues(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo

        repo.create_and_checkout("feature/issue-1", agent)
        repo.checkout(agent)

        repo.create_and_checkout("feature/issue-2", agent)
        (repo.path / "work.py").write_text("work\n")
        repo.stage_all()
        repo.commit("issue 2 work")
        repo.checkout(agent)

        recovery = BranchRecovery(repo, agent)
        results = recovery.classify_all([1, 2, 99])

        assert results[1].state == BranchState.EMPTY
        assert results[2].state == BranchState.COMMITS_ONLY
        assert results[99].state == BranchState.ABSENT


class TestDiscardAndRestart:
    def test_discard_dirty_branch(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-3", agent)
        (repo.path / "wip.py").write_text("partial\n")

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert not repo.branch_exists("feature/issue-3")
        assert repo.current_branch() == agent
        assert not repo.is_dirty()
        assert not (repo.path / "wip.py").exists()

    def test_discard_branch_with_commits(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-3", agent)
        (repo.path / "impl.py").write_text("implementation\n")
        repo.stage_all()
        repo.commit("implement")
        repo.checkout(agent)

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert not repo.branch_exists("feature/issue-3")
        assert repo.current_branch() == agent

    def test_discard_empty_branch(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-3", agent)
        repo.checkout(agent)

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert not repo.branch_exists("feature/issue-3")
        assert repo.current_branch() == agent

    def test_discard_nonexistent_branch_is_noop(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        recovery = BranchRecovery(repo, agent)

        recovery.discard_and_restart(999)

        assert repo.current_branch() == agent

    def test_discard_preserves_agent_branch(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        agent_sha = repo.rev_parse("HEAD")

        repo.create_and_checkout("feature/issue-3", agent)
        (repo.path / "impl.py").write_text("implementation\n")
        repo.stage_all()
        repo.commit("implement")

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert repo.rev_parse("HEAD") == agent_sha

    def test_discard_dirty_with_staged_and_unstaged(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-3", agent)
        (repo.path / "staged.py").write_text("staged\n")
        repo.stage("staged.py")
        (repo.path / "unstaged.py").write_text("unstaged\n")

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert not repo.branch_exists("feature/issue-3")
        assert repo.current_branch() == agent
        assert not repo.is_dirty()

    def test_discard_when_on_different_branch(self, agent_repo: tuple[GitRepo, str]) -> None:
        """Discard works even when a third branch is checked out."""
        repo, agent = agent_repo
        repo.create_and_checkout("feature/issue-3", agent)
        (repo.path / "impl.py").write_text("implementation\n")
        repo.stage_all()
        repo.commit("implement")

        repo.create_and_checkout("feature/issue-4", agent)

        recovery = BranchRecovery(repo, agent)
        recovery.discard_and_restart(3)

        assert not repo.branch_exists("feature/issue-3")
        assert repo.current_branch() == agent


class TestGitRepoResetAndClean:
    """Tests for the reset_hard and clean_untracked methods added to GitRepo."""

    def test_reset_hard_discards_staged(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, _ = agent_repo
        (repo.path / "staged.py").write_text("staged\n")
        repo.stage("staged.py")
        assert repo.is_dirty()

        repo.reset_hard()

        assert not (repo.path / "staged.py").exists()
        assert not repo.is_dirty()

    def test_clean_untracked_removes_new_files(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, _ = agent_repo
        (repo.path / "untracked.py").write_text("new\n")
        assert repo.is_dirty()

        repo.clean_untracked()

        assert not (repo.path / "untracked.py").exists()

    def test_clean_untracked_removes_directories(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, _ = agent_repo
        subdir = repo.path / "newdir"
        subdir.mkdir()
        (subdir / "file.py").write_text("nested\n")

        repo.clean_untracked()

        assert not subdir.exists()
