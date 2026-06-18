from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.git import GitError, GitRepo, MergeConflictError, PathBoundaryError


@pytest.fixture()
def git_repo(tmp_path: Path) -> GitRepo:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return GitRepo(tmp_path)


class TestConstruction:
    def test_valid_repo(self, git_repo: GitRepo) -> None:
        assert git_repo.path.is_dir()

    def test_not_a_repo(self, tmp_path: Path) -> None:
        with pytest.raises(PathBoundaryError, match="Not a git repository"):
            GitRepo(tmp_path)


class TestBranches:
    def test_create_and_checkout(self, git_repo: GitRepo) -> None:
        git_repo.create_branch("feature")
        git_repo.checkout("feature")
        assert git_repo.current_branch() == "feature"

    def test_create_and_checkout_shorthand(self, git_repo: GitRepo) -> None:
        git_repo.create_and_checkout("feature")
        assert git_repo.current_branch() == "feature"

    def test_create_from_start_point(self, git_repo: GitRepo) -> None:
        main_sha = git_repo.rev_parse("HEAD")
        (git_repo.path / "extra.txt").write_text("extra\n")
        git_repo.stage_all()
        git_repo.commit("second commit")

        git_repo.create_branch("from-initial", main_sha)
        git_repo.checkout("from-initial")
        assert git_repo.rev_parse("HEAD") == main_sha

    def test_delete_merged_branch(self, git_repo: GitRepo) -> None:
        git_repo.create_and_checkout("to-delete")
        (git_repo.path / "file.txt").write_text("content\n")
        git_repo.stage_all()
        git_repo.commit("add file")

        main = "main" if git_repo.branch_exists("main") else "master"
        git_repo.checkout(main)
        git_repo.merge("to-delete")
        git_repo.delete_branch("to-delete")
        assert not git_repo.branch_exists("to-delete")

    def test_delete_unmerged_branch_force(self, git_repo: GitRepo) -> None:
        git_repo.create_and_checkout("unmerged")
        (git_repo.path / "file.txt").write_text("content\n")
        git_repo.stage_all()
        git_repo.commit("add file")

        main = "main" if git_repo.branch_exists("main") else "master"
        git_repo.checkout(main)
        git_repo.delete_branch("unmerged", force=True)
        assert not git_repo.branch_exists("unmerged")

    def test_delete_unmerged_branch_no_force_fails(self, git_repo: GitRepo) -> None:
        git_repo.create_and_checkout("unmerged")
        (git_repo.path / "file.txt").write_text("content\n")
        git_repo.stage_all()
        git_repo.commit("add file")

        main = "main" if git_repo.branch_exists("main") else "master"
        git_repo.checkout(main)
        with pytest.raises(GitError):
            git_repo.delete_branch("unmerged")

    def test_branch_exists(self, git_repo: GitRepo) -> None:
        assert git_repo.branch_exists(git_repo.current_branch())
        assert not git_repo.branch_exists("nonexistent")


class TestMerge:
    def test_clean_merge(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        git_repo.create_and_checkout("feature")
        (git_repo.path / "feature.txt").write_text("feature\n")
        git_repo.stage_all()
        git_repo.commit("add feature")

        git_repo.checkout(main)
        git_repo.merge("feature")

        assert (git_repo.path / "feature.txt").exists()

    def test_merge_conflict(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        (git_repo.path / "conflict.txt").write_text("main version\n")
        git_repo.stage_all()
        git_repo.commit("add conflict.txt on main")

        git_repo.create_and_checkout("feature", main + "~1")
        (git_repo.path / "conflict.txt").write_text("feature version\n")
        git_repo.stage_all()
        git_repo.commit("add conflict.txt on feature")

        git_repo.checkout(main)
        with pytest.raises(MergeConflictError):
            git_repo.merge("feature")

        git_repo.abort_merge()

    def test_is_merged(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        git_repo.create_and_checkout("merged-branch")
        (git_repo.path / "merged.txt").write_text("merged\n")
        git_repo.stage_all()
        git_repo.commit("add merged file")

        git_repo.checkout(main)
        assert not git_repo.is_merged("merged-branch", main)

        git_repo.merge("merged-branch")
        assert git_repo.is_merged("merged-branch", main)


class TestStagingAndCommitting:
    def test_stage_and_commit(self, git_repo: GitRepo) -> None:
        (git_repo.path / "new.txt").write_text("new\n")
        git_repo.stage("new.txt")
        sha = git_repo.commit("add new file")
        assert len(sha) == 40
        assert not git_repo.is_dirty()

    def test_stage_all(self, git_repo: GitRepo) -> None:
        (git_repo.path / "a.txt").write_text("a\n")
        (git_repo.path / "b.txt").write_text("b\n")
        git_repo.stage_all()
        git_repo.commit("add two files")
        assert (git_repo.path / "a.txt").exists()
        assert (git_repo.path / "b.txt").exists()

    def test_stage_outside_boundary(self, git_repo: GitRepo) -> None:
        with pytest.raises(PathBoundaryError, match="outside repo boundary"):
            git_repo.stage("../../etc/passwd")

    def test_stage_sibling_directory_prefix_collision(self, git_repo: GitRepo) -> None:
        sibling = git_repo.path.parent / (git_repo.path.name + "_evil")
        sibling.mkdir()
        (sibling / "payload.txt").write_text("bad")
        relative = os.path.relpath(sibling / "payload.txt", git_repo.path)
        with pytest.raises(PathBoundaryError, match="outside repo boundary"):
            git_repo.stage(relative)

    def test_commit_on_clean_tree_fails(self, git_repo: GitRepo) -> None:
        with pytest.raises(GitError):
            git_repo.commit("nothing to commit")


class TestDirtyDetection:
    def test_clean_repo(self, git_repo: GitRepo) -> None:
        assert not git_repo.is_dirty()

    def test_untracked_file(self, git_repo: GitRepo) -> None:
        (git_repo.path / "untracked.txt").write_text("untracked\n")
        assert git_repo.is_dirty()

    def test_modified_file(self, git_repo: GitRepo) -> None:
        (git_repo.path / "README.md").write_text("modified\n")
        assert git_repo.is_dirty()

    def test_staged_file(self, git_repo: GitRepo) -> None:
        (git_repo.path / "staged.txt").write_text("staged\n")
        git_repo.stage("staged.txt")
        assert git_repo.is_dirty()


class TestCommitsBetween:
    def test_no_commits(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        git_repo.create_and_checkout("empty-branch")
        assert git_repo.commits_between(main, "empty-branch") == []

    def test_multiple_commits(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        git_repo.create_and_checkout("multi")

        (git_repo.path / "one.txt").write_text("1\n")
        git_repo.stage_all()
        git_repo.commit("first")

        (git_repo.path / "two.txt").write_text("2\n")
        git_repo.stage_all()
        git_repo.commit("second")

        commits = git_repo.commits_between(main, "multi")
        assert len(commits) == 2


class TestDiffStat:
    def test_diff_stat(self, git_repo: GitRepo) -> None:
        main = git_repo.current_branch()
        git_repo.create_and_checkout("diff-branch")
        (git_repo.path / "new.txt").write_text("content\n")
        git_repo.stage_all()
        git_repo.commit("add file")

        stat = git_repo.diff_stat(main, "diff-branch")
        assert "new.txt" in stat


class TestFetch:
    def test_fetch_no_remote_fails(self, git_repo: GitRepo) -> None:
        with pytest.raises(GitError):
            git_repo.fetch()
