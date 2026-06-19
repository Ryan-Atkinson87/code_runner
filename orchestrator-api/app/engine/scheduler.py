from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class IssueTask:
    issue_number: int
    repo_name: str
    depends_on: list[int] = field(default_factory=list)


class WaveScheduler:
    """Wave concurrency scheduler (Spec §18.6).

    - Parallel across repos, sequential within each repo.
    - Configurable cap on total in-flight issues (default = repo count).
    - Cap can be stepped down (3→2→1→pause) by the usage monitor (§18.7).
    - Cross-repo dependencies respected: a dependent issue waits until
      its dependency reaches done.
    """

    def __init__(self, cap: int | None = None) -> None:
        self._explicit_cap = cap
        self._cap: int = cap or 0
        self._repo_locks: dict[str, asyncio.Lock] = {}
        self._admission = asyncio.Semaphore(0)
        self._done: set[int] = set()
        self._done_event = asyncio.Event()
        self._paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()

    def _lock_for(self, repo_name: str) -> asyncio.Lock:
        if repo_name not in self._repo_locks:
            self._repo_locks[repo_name] = asyncio.Lock()
        return self._repo_locks[repo_name]

    def _effective_cap(self, repo_count: int) -> int:
        if self._explicit_cap is not None:
            return self._explicit_cap
        return repo_count

    async def run_wave(
        self,
        tasks: list[IssueTask],
        execute: Callable[[IssueTask], Awaitable[T]],
    ) -> dict[int, T]:
        """Schedule and run all tasks in dependency order.

        Returns a dict mapping issue_number to the result of execute().
        """
        if not tasks:
            return {}

        repo_names = {t.repo_name for t in tasks}
        self._cap = self._effective_cap(len(repo_names))
        self._admission = asyncio.Semaphore(self._cap)
        self._done = set()
        self._done_event = asyncio.Event()

        results: dict[int, T] = {}
        exceptions: dict[int, Exception] = {}

        async def _run_task(task: IssueTask) -> None:
            await self._wait_for_dependencies(task)
            await self._pause_event.wait()
            await self._admission.acquire()
            try:
                repo_lock = self._lock_for(task.repo_name)
                async with repo_lock:
                    result = await execute(task)
                    results[task.issue_number] = result
            except Exception as exc:
                exceptions[task.issue_number] = exc
            finally:
                self._admission.release()
                self._done.add(task.issue_number)
                self._done_event.set()
                self._done_event = asyncio.Event()

        async with asyncio.TaskGroup() as tg:
            for task in tasks:
                tg.create_task(_run_task(task))

        if exceptions:
            first = next(iter(exceptions.values()))
            raise first

        return results

    async def _wait_for_dependencies(self, task: IssueTask) -> None:
        while True:
            unmet = [d for d in task.depends_on if d not in self._done]
            if not unmet:
                return
            await self._done_event.wait()

    def step_down_cap(self, new_cap: int) -> None:
        """Step the concurrency cap down (§18.7 usage lever).

        New admissions will be limited; in-flight tasks are not
        interrupted. Setting cap to 0 is equivalent to pause.
        """
        if new_cap <= 0:
            self.pause()
            return
        self._cap = new_cap
        self._explicit_cap = new_cap

    def pause(self) -> None:
        """Pause new task admission (hard pause floor)."""
        self._paused = True
        self._pause_event.clear()

    def resume(self) -> None:
        """Resume task admission after a pause."""
        self._paused = False
        self._pause_event.set()

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def is_paused(self) -> bool:
        return self._paused
