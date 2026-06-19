from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path


class MergeQueue:
    """Per-repo serialised merge queue (Spec §18.6).

    Diff and review steps may run concurrently; only the merge moment
    serialises. Acquire the lock for a repo before calling
    FeatureBranch.merge_into_agent().
    """

    def __init__(self) -> None:
        self._locks: dict[Path, asyncio.Lock] = {}

    def _lock_for(self, repo_path: Path) -> asyncio.Lock:
        if repo_path not in self._locks:
            self._locks[repo_path] = asyncio.Lock()
        return self._locks[repo_path]

    @asynccontextmanager
    async def serialise(self, repo_path: Path) -> AsyncIterator[None]:
        """Context manager that serialises merge access for a repo."""
        lock = self._lock_for(repo_path)
        async with lock:
            yield
