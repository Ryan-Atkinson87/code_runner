from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import StrEnum

from app.providers.adapter import ProviderAdapter
from app.providers.types import SessionOutcome, SessionRole
from app.usage.models import Meter

logger = logging.getLogger(__name__)

_RESET_BUFFER_SECONDS = 30.0
_INITIAL_PROBE_INTERVAL = 300.0  # 5 minutes
_MAX_PROBE_INTERVAL = 1800.0  # 30 minutes


class ResumeStrategy(StrEnum):
    SLEEP_UNTIL_RESET = "sleep_until_reset"
    PROBE_WITH_BACKOFF = "probe_with_backoff"


@dataclass(frozen=True, slots=True)
class ResumeAction:
    strategy: ResumeStrategy
    wait_seconds: float
    probe_model: str | None = None


@dataclass(slots=True)
class BackoffState:
    interval: float = _INITIAL_PROBE_INTERVAL
    _max_interval: float = field(default=_MAX_PROBE_INTERVAL, repr=False)

    def next_interval(self) -> float:
        current = self.interval
        self.interval = min(self.interval * 2, self._max_interval)
        return current

    def reset(self) -> None:
        self.interval = _INITIAL_PROBE_INTERVAL


class UsagePauseManager:
    """Hard pause and two-tier automatic resume (Spec §6.3, §6.4)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def set_paused(self, run_id: int, governing: Meter) -> None:
        self._conn.execute(
            """INSERT INTO usage_pauses
                   (run_id, governing_meter_kind, governing_utilisation, resets_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (run_id)
               DO UPDATE SET governing_meter_kind = excluded.governing_meter_kind,
                            governing_utilisation = excluded.governing_utilisation,
                            resets_at = excluded.resets_at,
                            paused_at = datetime('now'),
                            resumed_at = NULL
            """,
            (run_id, governing.kind, governing.utilisation, governing.resets_at),
        )
        self._conn.commit()
        logger.info(
            "Run %d paused: governing meter %s at %.1f%%",
            run_id,
            governing.kind,
            governing.utilisation,
        )

    def set_resumed(self, run_id: int) -> None:
        self._conn.execute(
            "UPDATE usage_pauses SET resumed_at = datetime('now') WHERE run_id = ?",
            (run_id,),
        )
        self._conn.commit()
        logger.info("Run %d resumed", run_id)

    def is_paused(self, run_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM usage_pauses WHERE run_id = ? AND resumed_at IS NULL",
            (run_id,),
        ).fetchone()
        return row is not None

    def get_pause_state(self, run_id: int) -> tuple[str, float, float | None] | None:
        """Return (meter_kind, utilisation, resets_at) or None."""
        row = self._conn.execute(
            """SELECT governing_meter_kind, governing_utilisation, resets_at
               FROM usage_pauses
               WHERE run_id = ? AND resumed_at IS NULL""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return (str(row[0]), float(row[1]), float(row[2]) if row[2] is not None else None)

    def next_resume_action(
        self,
        run_id: int,
        backoff: BackoffState,
        *,
        now: float | None = None,
    ) -> ResumeAction | None:
        """Calculate the next action for resuming a paused run."""
        state = self.get_pause_state(run_id)
        if state is None:
            return None

        _kind, _util, resets_at = state
        ts = now if now is not None else time.time()

        if resets_at is not None:
            wait = max(resets_at - ts + _RESET_BUFFER_SECONDS, 0.0)
            return ResumeAction(
                strategy=ResumeStrategy.SLEEP_UNTIL_RESET,
                wait_seconds=wait,
            )

        return ResumeAction(
            strategy=ResumeStrategy.PROBE_WITH_BACKOFF,
            wait_seconds=backoff.next_interval(),
        )


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def wait_for_resume(
    manager: UsagePauseManager,
    run_id: int,
    adapter: ProviderAdapter,
    probe_model: str,
    *,
    now_fn: callable = time.time,  # type: ignore[type-arg]
    sleep_fn: callable = _default_sleep,  # type: ignore[type-arg]
) -> None:
    """Block until usage resets, then mark resumed.

    Uses the two-tier strategy: sleep-until-reset when resets_at is
    known; probe with exponential backoff otherwise.
    """
    backoff = BackoffState()

    while manager.is_paused(run_id):
        action = manager.next_resume_action(run_id, backoff, now=now_fn())
        if action is None:
            break

        if action.strategy == ResumeStrategy.SLEEP_UNTIL_RESET:
            if action.wait_seconds > 0:
                logger.info(
                    "Run %d: sleeping %.0fs until meter reset",
                    run_id,
                    action.wait_seconds,
                )
                await sleep_fn(action.wait_seconds)
            manager.set_resumed(run_id)
            break

        logger.info(
            "Run %d: probing %s after %.0fs backoff",
            run_id,
            probe_model,
            action.wait_seconds,
        )
        await sleep_fn(action.wait_seconds)

        available = await _probe_model(adapter, probe_model)
        if available:
            backoff.reset()
            manager.set_resumed(run_id)
            break


async def _probe_model(adapter: ProviderAdapter, model: str) -> bool:
    """Issue the cheapest possible call to check model availability."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        try:
            result = await adapter.run_session(
                workdir=workdir,
                role=SessionRole.IMPLEMENTOR,
                model=model,
                allowed_tools=[],
                prompt="Reply with OK.",
                context_files=[],
            )
            return result.outcome == SessionOutcome.COMPLETED
        except Exception:
            logger.debug("Probe for %s failed", model, exc_info=True)
            return False
