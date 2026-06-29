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

    def prune(self, active_paths: set[Path]) -> None:
        """Remove lock entries for paths not in *active_paths* and not currently held.

        Call after a wave completes to keep the dict bounded to the active repo set.
        Only idle locks (not currently acquired) are removed; held locks are left
        in place so no in-flight merge is affected.
        """
        stale = [
            p for p in list(self._locks) if p not in active_paths and not self._locks[p].locked()
        ]
        for path in stale:
            del self._locks[path]
