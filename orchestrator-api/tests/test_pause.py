from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.db.store import StateStore
from app.providers.types import SessionOutcome, SessionResult
from app.usage.models import Meter, MeterKind
from app.usage.pause import (
    BackoffState,
    ResumeStrategy,
    UsagePauseManager,
    wait_for_resume,
)


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[StateStore]:
    s = StateStore(tmp_path / "test.db")
    s.open()
    yield s
    s.close()


@pytest.fixture()
def run_id(store: StateStore) -> int:
    store.conn.execute(
        "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
        ("test-project", "phase-4", "running"),
    )
    store.conn.commit()
    row = store.conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


@pytest.fixture()
def manager(store: StateStore) -> UsagePauseManager:
    return UsagePauseManager(store.conn)


class TestUsagePauseManager:
    def test_set_paused(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0, resets_at=9999.0)
        manager.set_paused(run_id, meter)
        assert manager.is_paused(run_id) is True

    def test_not_paused_initially(self, manager: UsagePauseManager, run_id: int) -> None:
        assert manager.is_paused(run_id) is False

    def test_set_resumed(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0)
        manager.set_paused(run_id, meter)
        assert manager.is_paused(run_id) is True

        manager.set_resumed(run_id)
        assert manager.is_paused(run_id) is False

    def test_get_pause_state(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.SEVEN_DAY, utilisation=90.0, resets_at=2000.0)
        manager.set_paused(run_id, meter)

        state = manager.get_pause_state(run_id)
        assert state is not None
        kind, util, resets_at = state
        assert kind == MeterKind.SEVEN_DAY
        assert util == 90.0
        assert resets_at == 2000.0

    def test_get_pause_state_none_when_not_paused(
        self, manager: UsagePauseManager, run_id: int
    ) -> None:
        assert manager.get_pause_state(run_id) is None

    def test_set_paused_overwrites(self, manager: UsagePauseManager, run_id: int) -> None:
        m1 = Meter(kind=MeterKind.FIVE_HOUR, utilisation=80.0)
        manager.set_paused(run_id, m1)

        m2 = Meter(kind=MeterKind.SEVEN_DAY, utilisation=95.0, resets_at=5000.0)
        manager.set_paused(run_id, m2)

        state = manager.get_pause_state(run_id)
        assert state is not None
        assert state[0] == MeterKind.SEVEN_DAY
        assert state[1] == 95.0


class TestResumeAction:
    def test_reset_known_sleep(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0, resets_at=2000.0)
        manager.set_paused(run_id, meter)

        backoff = BackoffState()
        action = manager.next_resume_action(run_id, backoff, now=1000.0)
        assert action is not None
        assert action.strategy == ResumeStrategy.SLEEP_UNTIL_RESET
        assert action.wait_seconds == pytest.approx(1030.0, abs=1.0)

    def test_reset_known_past_time(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0, resets_at=500.0)
        manager.set_paused(run_id, meter)

        backoff = BackoffState()
        action = manager.next_resume_action(run_id, backoff, now=1000.0)
        assert action is not None
        assert action.strategy == ResumeStrategy.SLEEP_UNTIL_RESET
        assert action.wait_seconds == 0.0

    def test_reset_unknown_probe(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0)
        manager.set_paused(run_id, meter)

        backoff = BackoffState()
        action = manager.next_resume_action(run_id, backoff)
        assert action is not None
        assert action.strategy == ResumeStrategy.PROBE_WITH_BACKOFF
        assert action.wait_seconds == 300.0

    def test_not_paused_returns_none(self, manager: UsagePauseManager, run_id: int) -> None:
        backoff = BackoffState()
        action = manager.next_resume_action(run_id, backoff)
        assert action is None


class TestBackoffState:
    def test_sequence(self) -> None:
        b = BackoffState()
        assert b.next_interval() == 300.0
        assert b.next_interval() == 600.0
        assert b.next_interval() == 1200.0
        assert b.next_interval() == 1800.0
        assert b.next_interval() == 1800.0

    def test_reset_on_success(self) -> None:
        b = BackoffState()
        b.next_interval()
        b.next_interval()
        b.reset()
        assert b.next_interval() == 300.0

    def test_cap_at_max(self) -> None:
        b = BackoffState()
        for _ in range(20):
            b.next_interval()
        assert b.interval == 1800.0


async def _noop_sleep(_seconds: float) -> None:
    pass


class TestWaitForResume:
    @pytest.mark.anyio
    async def test_reset_known_resumes_immediately_past(
        self, manager: UsagePauseManager, run_id: int
    ) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0, resets_at=500.0)
        manager.set_paused(run_id, meter)

        adapter = AsyncMock()
        await wait_for_resume(
            manager,
            run_id,
            adapter,
            "claude-sonnet-4-6",
            now_fn=lambda: 1000.0,
            sleep_fn=_noop_sleep,
        )

        assert manager.is_paused(run_id) is False
        adapter.run_session.assert_not_called()

    @pytest.mark.anyio
    async def test_probe_success_resumes(self, manager: UsagePauseManager, run_id: int) -> None:
        meter = Meter(kind=MeterKind.FIVE_HOUR, utilisation=85.0)
        manager.set_paused(run_id, meter)

        adapter = AsyncMock()
        adapter.run_session.return_value = SessionResult(outcome=SessionOutcome.COMPLETED)

        await wait_for_resume(
            manager,
            run_id,
            adapter,
            "claude-sonnet-4-6",
            now_fn=lambda: 1000.0,
            sleep_fn=_noop_sleep,
        )

        assert manager.is_paused(run_id) is False
        adapter.run_session.assert_called_once()

    @pytest.mark.anyio
    async def test_probe_targets_specific_model(
        self, manager: UsagePauseManager, run_id: int
    ) -> None:
        meter = Meter(kind=MeterKind.SEVEN_DAY_OPUS, utilisation=90.0)
        manager.set_paused(run_id, meter)

        adapter = AsyncMock()
        adapter.run_session.return_value = SessionResult(outcome=SessionOutcome.COMPLETED)

        await wait_for_resume(
            manager,
            run_id,
            adapter,
            "claude-opus-4-6",
            now_fn=lambda: 1000.0,
            sleep_fn=_noop_sleep,
        )

        call_kwargs = adapter.run_session.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"
        assert manager.is_paused(run_id) is False
