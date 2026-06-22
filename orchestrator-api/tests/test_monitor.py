from __future__ import annotations

from pathlib import Path

import pytest

from app.db.store import StateStore
from app.engine.scheduler import WaveScheduler
from app.usage.models import Meter, MeterKind, UsageSnapshot
from app.usage.monitor import UsageMonitor
from app.usage.pause import UsagePauseManager
from app.usage.policy import PolicyAction, UsagePolicy
from app.usage.reader import UsageReader


class FakeReader(UsageReader):
    """Test reader that returns configurable snapshots."""

    def __init__(self, utilisation: float = 30.0) -> None:
        self.utilisation = utilisation
        self.call_count = 0

    async def read(self) -> UsageSnapshot:
        self.call_count += 1
        return UsageSnapshot(
            meters=[Meter(kind=MeterKind.FIVE_HOUR, utilisation=self.utilisation)],
            provider="claude",
            plan="pro",
            timestamp=1.0,
        )


class FailingReader(UsageReader):
    async def read(self) -> UsageSnapshot:
        raise ConnectionError("Network down")


@pytest.fixture()
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "test.db")
    s.open()
    yield s  # type: ignore[misc]
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


class TestUsageMonitor:
    @pytest.mark.anyio
    async def test_check_below_threshold(self) -> None:
        reader = FakeReader(utilisation=30.0)
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
        )
        result = await monitor.check()
        assert result.action == PolicyAction.PROCEED
        assert result.state.governing is not None
        assert result.state.governing.utilisation == 30.0
        assert result.error is None

    @pytest.mark.anyio
    async def test_check_at_threshold(self) -> None:
        reader = FakeReader(utilisation=85.0)
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
        )
        result = await monitor.check()
        assert result.action == PolicyAction.PAUSE
        assert result.state.threshold is not None
        assert result.state.threshold.reached is True

    @pytest.mark.anyio
    async def test_check_with_override(self) -> None:
        reader = FakeReader(utilisation=90.0)
        policy = UsagePolicy()
        policy.set_override(True)
        monitor = UsageMonitor(
            reader=reader,
            policy=policy,
            scheduler=WaveScheduler(cap=3),
        )
        result = await monitor.check()
        assert result.action == PolicyAction.PROCEED

    @pytest.mark.anyio
    async def test_check_steps_cap(self) -> None:
        reader = FakeReader(utilisation=70.0)
        scheduler = WaveScheduler(cap=3)
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=scheduler,
        )
        result = await monitor.check()
        assert result.state.cap_step is not None
        assert result.state.cap_step.new_cap == 2

    @pytest.mark.anyio
    async def test_check_sets_pause_state(
        self, store: StateStore, run_id: int
    ) -> None:
        reader = FakeReader(utilisation=85.0)
        pause_mgr = UsagePauseManager(store.conn)
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
            pause_manager=pause_mgr,
        )
        await monitor.check(run_id=run_id)
        assert pause_mgr.is_paused(run_id) is True

    @pytest.mark.anyio
    async def test_check_read_failure_degrades(self) -> None:
        reader = FailingReader()
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
        )
        result = await monitor.check()
        assert result.action == PolicyAction.PROCEED
        assert result.error is not None
        assert "Network down" in result.error

    @pytest.mark.anyio
    async def test_state_exposed_for_ui(self) -> None:
        reader = FakeReader(utilisation=60.0)
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
        )
        assert monitor.state is None

        await monitor.check()

        assert monitor.state is not None
        assert monitor.state.snapshot is not None
        assert monitor.state.governing is not None
        assert MeterKind.FIVE_HOUR in monitor.state.applicable_meter_kinds


class TestProviderSwitch:
    @pytest.mark.anyio
    async def test_switch_reader(self) -> None:
        reader1 = FakeReader(utilisation=30.0)
        monitor = UsageMonitor(
            reader=reader1,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
        )
        await monitor.check()
        assert reader1.call_count == 1

        reader2 = FakeReader(utilisation=50.0)
        monitor.switch_reader(reader2, "claude", "api")
        await monitor.check()

        assert reader2.call_count == 1
        assert monitor.state is not None
        assert MeterKind.API_BUDGET in monitor.state.applicable_meter_kinds

    @pytest.mark.anyio
    async def test_switch_reloads_meter_set(self) -> None:
        reader = FakeReader()
        monitor = UsageMonitor(
            reader=reader,
            policy=UsagePolicy(),
            scheduler=WaveScheduler(cap=3),
            provider="claude",
            plan="pro",
        )
        await monitor.check()
        assert MeterKind.FIVE_HOUR in monitor.state.applicable_meter_kinds  # type: ignore[union-attr]

        monitor.switch_reader(reader, "claude", "api")
        await monitor.check()
        assert MeterKind.API_BUDGET in monitor.state.applicable_meter_kinds  # type: ignore[union-attr]
        assert MeterKind.FIVE_HOUR not in monitor.state.applicable_meter_kinds  # type: ignore[union-attr]


class TestEndToEndSimulation:
    """Drives a simulated monitor through the full threshold→cap→pause→resume flow."""

    @pytest.mark.anyio
    async def test_full_cycle(self, store: StateStore, run_id: int) -> None:
        reader = FakeReader(utilisation=30.0)
        scheduler = WaveScheduler(cap=3)
        pause_mgr = UsagePauseManager(store.conn)
        policy = UsagePolicy()
        monitor = UsageMonitor(
            reader=reader,
            policy=policy,
            scheduler=scheduler,
            pause_manager=pause_mgr,
        )

        # Phase 1: Low usage — proceed, cap=3
        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PROCEED
        assert scheduler.cap == 3
        assert pause_mgr.is_paused(run_id) is False

        # Phase 2: Climbing — cap steps down
        reader.utilisation = 65.0
        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PROCEED
        assert scheduler.cap == 2

        reader.utilisation = 75.0
        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PROCEED
        assert scheduler.cap == 1

        # Phase 3: Threshold — pause
        reader.utilisation = 82.0
        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PAUSE
        assert scheduler.is_paused is True
        assert pause_mgr.is_paused(run_id) is True

        # Phase 4: Verify pause state is observable
        state = pause_mgr.get_pause_state(run_id)
        assert state is not None
        assert state[0] == MeterKind.FIVE_HOUR

        # Phase 5: Simulate reset — resume
        pause_mgr.set_resumed(run_id)
        scheduler.resume()
        reader.utilisation = 10.0
        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PROCEED
        assert pause_mgr.is_paused(run_id) is False

    @pytest.mark.anyio
    async def test_override_bypasses_full_chain(
        self, store: StateStore, run_id: int
    ) -> None:
        reader = FakeReader(utilisation=90.0)
        scheduler = WaveScheduler(cap=3)
        pause_mgr = UsagePauseManager(store.conn)
        policy = UsagePolicy()
        policy.set_override(True)

        monitor = UsageMonitor(
            reader=reader,
            policy=policy,
            scheduler=scheduler,
            pause_manager=pause_mgr,
        )

        result = await monitor.check(run_id=run_id)
        assert result.action == PolicyAction.PROCEED
        assert pause_mgr.is_paused(run_id) is False
