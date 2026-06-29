from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.git import GitRepo, MergeConflictError
from app.git.feature_branch import FeatureBranch
from app.git.merge_queue import MergeQueue


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def agent_repo(tmp_path: Path) -> tuple[GitRepo, str]:
    """A local repo with an agent branch checked out, ready for feature branches."""
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


class TestCreate:
    def test_creates_feature_branch_from_agent(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 42)

        fb.create()

        assert repo.current_branch() == "feature/issue-42"
        assert repo.branch_exists(fb.name)

    def test_branch_starts_at_agent_head(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        (repo.path / "agent-work.txt").write_text("agent\n")
        repo.stage_all()
        repo.commit("agent commit")
        agent_sha = repo.rev_parse("HEAD")

        fb = FeatureBranch(repo, agent, 7)
        fb.create()

        assert repo.rev_parse("HEAD") == agent_sha

    def test_multiple_feature_branches_coexist(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb1 = FeatureBranch(repo, agent, 1)
        fb2 = FeatureBranch(repo, agent, 2)

        fb1.create()
        repo.checkout(agent)
        fb2.create()

        assert repo.branch_exists(fb1.name)
        assert repo.branch_exists(fb2.name)


class TestDiff:
    def test_diff_shows_changes(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 10)
        fb.create()

        (repo.path / "new_file.py").write_text("print('hello')\n")
        repo.stage_all()
        repo.commit("add new file")

        diff = fb.diff()

        assert "new_file.py" in diff
        assert "+print('hello')" in diff

    def test_diff_empty_when_no_changes(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 10)
        fb.create()

        diff = fb.diff()

        assert diff == ""

    def test_diff_stat_shows_summary(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 10)
        fb.create()

        (repo.path / "a.py").write_text("a\n")
        (repo.path / "b.py").write_text("b\n")
        repo.stage_all()
        repo.commit("add two files")

        stat = fb.diff_stat()

        assert "a.py" in stat
        assert "b.py" in stat

    def test_diff_spans_multiple_commits(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 10)
        fb.create()

        (repo.path / "first.py").write_text("1\n")
        repo.stage_all()
        repo.commit("first commit")

        (repo.path / "second.py").write_text("2\n")
        repo.stage_all()
        repo.commit("second commit")

        diff = fb.diff()

        assert "first.py" in diff
        assert "second.py" in diff


class TestMergeIntoAgent:
    def test_clean_merge_returns_sha(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 5)
        fb.create()

        (repo.path / "feature.py").write_text("feature\n")
        repo.stage_all()
        repo.commit("implement feature")

        sha = fb.merge_into_agent()

        assert len(sha) == 40
        assert repo.current_branch() == agent
        assert (repo.path / "feature.py").exists()

    def test_feature_branch_deleted_after_merge(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 5)
        fb.create()

        (repo.path / "feature.py").write_text("feature\n")
        repo.stage_all()
        repo.commit("implement feature")

        fb.merge_into_agent()

        assert not repo.branch_exists(fb.name)

    def test_merge_commit_message_references_issue(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 42)
        fb.create()

        (repo.path / "feature.py").write_text("feature\n")
        repo.stage_all()
        repo.commit("implement feature")

        fb.merge_into_agent()

        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=repo.path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "#42" in result.stdout

    def test_merge_conflict_raises_and_preserves_agent(
        self, agent_repo: tuple[GitRepo, str]
    ) -> None:
        repo, agent = agent_repo

        (repo.path / "conflict.txt").write_text("agent version\n")
        repo.stage_all()
        repo.commit("agent adds conflict.txt")

        fb = FeatureBranch(repo, agent, 99)
        fb.create()

        _run_git(repo.path, "reset", "--hard", "HEAD~1")
        (repo.path / "conflict.txt").write_text("feature version\n")
        repo.stage_all()
        repo.commit("feature adds conflict.txt differently")

        with pytest.raises(MergeConflictError):
            fb.merge_into_agent()

        assert repo.current_branch() == fb.name
        assert repo.branch_exists(agent)
        assert not repo.is_dirty()

    def test_agent_branch_unchanged_after_conflict(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo

        (repo.path / "conflict.txt").write_text("agent version\n")
        repo.stage_all()
        repo.commit("agent adds conflict.txt")
        agent_sha = repo.rev_parse("HEAD")

        fb = FeatureBranch(repo, agent, 99)
        fb.create()

        _run_git(repo.path, "reset", "--hard", "HEAD~1")
        (repo.path / "conflict.txt").write_text("feature version\n")
        repo.stage_all()
        repo.commit("feature version")

        with pytest.raises(MergeConflictError):
            fb.merge_into_agent()

        repo.checkout(agent)
        assert repo.rev_parse("HEAD") == agent_sha

    def test_sequential_merges_preserve_all_work(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo

        fb1 = FeatureBranch(repo, agent, 1)
        fb1.create()
        (repo.path / "feature1.py").write_text("one\n")
        repo.stage_all()
        repo.commit("issue 1")

        repo.checkout(agent)

        fb2 = FeatureBranch(repo, agent, 2)
        fb2.create()
        (repo.path / "feature2.py").write_text("two\n")
        repo.stage_all()
        repo.commit("issue 2")

        repo.checkout(fb1.name)
        fb1.merge_into_agent()

        repo.checkout(fb2.name)
        fb2.merge_into_agent()

        assert (repo.path / "feature1.py").exists()
        assert (repo.path / "feature2.py").exists()
        assert not repo.branch_exists(fb1.name)
        assert not repo.branch_exists(fb2.name)


class TestDiscard:
    def test_discard_removes_feature_branch(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        fb = FeatureBranch(repo, agent, 3)
        fb.create()

        (repo.path / "wip.py").write_text("wip\n")
        repo.stage_all()
        repo.commit("wip")

        fb.discard()

        assert not repo.branch_exists(fb.name)
        assert repo.current_branch() == agent

    def test_discard_does_not_affect_agent(self, agent_repo: tuple[GitRepo, str]) -> None:
        repo, agent = agent_repo
        agent_sha = repo.rev_parse("HEAD")

        fb = FeatureBranch(repo, agent, 3)
        fb.create()
        (repo.path / "wip.py").write_text("wip\n")
        repo.stage_all()
        repo.commit("wip")

        fb.discard()

        assert repo.rev_parse("HEAD") == agent_sha
        assert not (repo.path / "wip.py").exists()


class TestProperties:
    def test_name(self) -> None:
        fb = FeatureBranch.__new__(FeatureBranch)
        fb._agent_branch = "code-runner/wave-1"
        fb._issue_number = 42
        fb._branch_name = "feature/issue-42"
        assert fb.name == "feature/issue-42"

    def test_agent_branch(self) -> None:
        fb = FeatureBranch.__new__(FeatureBranch)
        fb._agent_branch = "code-runner/wave-1"
        assert fb.agent_branch == "code-runner/wave-1"

    def test_issue_number(self) -> None:
        fb = FeatureBranch.__new__(FeatureBranch)
        fb._issue_number = 42
        assert fb.issue_number == 42


class TestMergeQueue:
    def test_serialises_concurrent_merges(self) -> None:
        queue = MergeQueue()
        repo_path = Path("/tmp/test-repo")
        order: list[int] = []

        async def merge_task(task_id: int) -> None:
            async with queue.serialise(repo_path):
                order.append(task_id)
                await asyncio.sleep(0.01)

        async def run() -> None:
            await asyncio.gather(merge_task(1), merge_task(2))

        asyncio.run(run())

        assert sorted(order) == [1, 2]
        assert len(order) == 2

    def test_different_repos_run_concurrently(self) -> None:
        queue = MergeQueue()
        repo_a = Path("/tmp/repo-a")
        repo_b = Path("/tmp/repo-b")
        timestamps: dict[str, list[float]] = {"a": [], "b": []}

        async def merge_task(repo: Path, key: str) -> None:
            async with queue.serialise(repo):
                timestamps[key].append(asyncio.get_event_loop().time())
                await asyncio.sleep(0.05)
                timestamps[key].append(asyncio.get_event_loop().time())

        async def run() -> None:
            await asyncio.gather(merge_task(repo_a, "a"), merge_task(repo_b, "b"))

        asyncio.run(run())

        a_start, a_end = timestamps["a"]
        b_start, b_end = timestamps["b"]
        assert a_start < b_end and b_start < a_end

    def test_same_repo_serialised(self) -> None:
        queue = MergeQueue()
        repo_path = Path("/tmp/test-repo")
        events: list[str] = []

        async def merge_task(task_id: int) -> None:
            async with queue.serialise(repo_path):
                events.append(f"start-{task_id}")
                await asyncio.sleep(0.02)
                events.append(f"end-{task_id}")

        async def run() -> None:
            await asyncio.gather(merge_task(1), merge_task(2))

        asyncio.run(run())

        start_1 = events.index("start-1")
        end_1 = events.index("end-1")
        start_2 = events.index("start-2")
        end_2 = events.index("end-2")
        assert (end_1 < start_2) or (end_2 < start_1)

    def test_prune_removes_idle_stale_entries(self) -> None:
        queue = MergeQueue()
        repo_a = Path("/tmp/repo-a")
        repo_b = Path("/tmp/repo-b")

        async def prime() -> None:
            async with queue.serialise(repo_a):
                pass
            async with queue.serialise(repo_b):
                pass

        asyncio.run(prime())
        assert len(queue._locks) == 2

        queue.prune(active_paths={repo_a})
        assert repo_a in queue._locks
        assert repo_b not in queue._locks

    def test_prune_preserves_held_locks(self) -> None:
        queue = MergeQueue()
        repo_path = Path("/tmp/held-repo")

        async def run() -> None:
            acquired = asyncio.Event()
            release = asyncio.Event()

            async def hold_lock() -> None:
                async with queue.serialise(repo_path):
                    acquired.set()
                    await release.wait()

            task = asyncio.create_task(hold_lock())
            await acquired.wait()
            queue.prune(active_paths=set())
            assert repo_path in queue._locks
            release.set()
            await task

        asyncio.run(run())

    def test_prune_does_not_grow_beyond_active_set(self) -> None:
        queue = MergeQueue()
        paths = [Path(f"/tmp/repo-{i}") for i in range(5)]

        async def prime_all() -> None:
            for p in paths:
                async with queue.serialise(p):
                    pass

        asyncio.run(prime_all())
        assert len(queue._locks) == 5

        active = set(paths[:2])
        queue.prune(active_paths=active)
        assert len(queue._locks) == 2
        assert set(queue._locks.keys()) == active
