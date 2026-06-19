from __future__ import annotations

import asyncio
import time

import pytest

from app.engine.scheduler import IssueTask, WaveScheduler


@pytest.fixture()
def scheduler() -> WaveScheduler:
    return WaveScheduler()


class TestParallelAcrossReposSequentialWithin:
    @pytest.mark.asyncio()
    async def test_two_repos_run_concurrently(self) -> None:
        order: list[str] = []

        async def execute(task: IssueTask) -> str:
            order.append(f"start-{task.issue_number}")
            await asyncio.sleep(0.05)
            order.append(f"end-{task.issue_number}")
            return f"done-{task.issue_number}"

        scheduler = WaveScheduler()
        tasks = [
            IssueTask(issue_number=1, repo_name="repo-a"),
            IssueTask(issue_number=2, repo_name="repo-b"),
        ]

        start = time.monotonic()
        results = await scheduler.run_wave(tasks, execute)
        elapsed = time.monotonic() - start

        assert len(results) == 2
        # Both should complete in ~50ms if truly parallel, not ~100ms
        assert elapsed < 0.15

    @pytest.mark.asyncio()
    async def test_same_repo_serialises(self) -> None:
        order: list[str] = []

        async def execute(task: IssueTask) -> str:
            order.append(f"start-{task.issue_number}")
            await asyncio.sleep(0.05)
            order.append(f"end-{task.issue_number}")
            return f"done-{task.issue_number}"

        scheduler = WaveScheduler()
        tasks = [
            IssueTask(issue_number=1, repo_name="repo-a"),
            IssueTask(issue_number=2, repo_name="repo-a"),
        ]

        results = await scheduler.run_wave(tasks, execute)
        assert len(results) == 2

        # Serialised: one must finish before the other starts
        start_indices = [
            i for i, v in enumerate(order) if v.startswith("start")
        ]
        end_indices = [
            i for i, v in enumerate(order) if v.startswith("end")
        ]
        # First end must come before second start
        assert end_indices[0] < start_indices[1]


class TestCapBehaviour:
    @pytest.mark.asyncio()
    async def test_cap_of_1_forces_full_sequencing(self) -> None:
        order: list[str] = []

        async def execute(task: IssueTask) -> str:
            order.append(f"start-{task.issue_number}")
            await asyncio.sleep(0.02)
            order.append(f"end-{task.issue_number}")
            return "ok"

        scheduler = WaveScheduler(cap=1)
        tasks = [
            IssueTask(issue_number=1, repo_name="repo-a"),
            IssueTask(issue_number=2, repo_name="repo-b"),
        ]

        await scheduler.run_wave(tasks, execute)

        # With cap=1, fully sequential
        assert order[0].startswith("start")
        assert order[1].startswith("end")
        assert order[2].startswith("start")
        assert order[3].startswith("end")

    @pytest.mark.asyncio()
    async def test_default_cap_equals_repo_count(self) -> None:
        scheduler = WaveScheduler()
        tasks = [
            IssueTask(issue_number=1, repo_name="repo-a"),
            IssueTask(issue_number=2, repo_name="repo-b"),
            IssueTask(issue_number=3, repo_name="repo-c"),
        ]

        async def execute(task: IssueTask) -> str:
            return "ok"

        await scheduler.run_wave(tasks, execute)
        assert scheduler.cap == 3


class TestCapStepDown:
    def test_step_down_updates_cap(self) -> None:
        scheduler = WaveScheduler(cap=3)
        scheduler.step_down_cap(2)
        assert scheduler.cap == 2

    def test_step_down_to_zero_pauses(self) -> None:
        scheduler = WaveScheduler(cap=3)
        scheduler.step_down_cap(0)
        assert scheduler.is_paused

    def test_resume_after_pause(self) -> None:
        scheduler = WaveScheduler(cap=3)
        scheduler.pause()
        assert scheduler.is_paused
        scheduler.resume()
        assert not scheduler.is_paused


class TestDependencies:
    @pytest.mark.asyncio()
    async def test_dependent_waits_for_dependency(self) -> None:
        order: list[str] = []

        async def execute(task: IssueTask) -> str:
            order.append(f"start-{task.issue_number}")
            await asyncio.sleep(0.03)
            order.append(f"end-{task.issue_number}")
            return "ok"

        scheduler = WaveScheduler()
        tasks = [
            IssueTask(issue_number=1, repo_name="repo-a"),
            IssueTask(
                issue_number=2,
                repo_name="repo-b",
                depends_on=[1],
            ),
        ]

        await scheduler.run_wave(tasks, execute)

        # Issue 2 must start after issue 1 ends
        end_1 = order.index("end-1")
        start_2 = order.index("start-2")
        assert end_1 < start_2


class TestEmptyWave:
    @pytest.mark.asyncio()
    async def test_empty_tasks_returns_empty(self) -> None:
        scheduler = WaveScheduler()

        async def execute(task: IssueTask) -> str:
            return "ok"

        results = await scheduler.run_wave([], execute)
        assert results == {}
