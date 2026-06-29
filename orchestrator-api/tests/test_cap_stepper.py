from __future__ import annotations

from app.engine.scheduler import WaveScheduler
from app.usage.cap_stepper import apply_cap_step, cap_for_utilisation
from app.usage.models import Meter, MeterKind, UsageSnapshot


def _snapshot(utilisation: float) -> UsageSnapshot:
    return UsageSnapshot(
        meters=[Meter(kind=MeterKind.FIVE_HOUR, utilisation=utilisation)],
        provider="claude",
        plan="pro",
        timestamp=1.0,
    )


class TestCapForUtilisation:
    def test_below_first_step(self) -> None:
        assert cap_for_utilisation(30.0) == 3

    def test_at_first_step(self) -> None:
        assert cap_for_utilisation(50.0) == 3

    def test_second_step(self) -> None:
        assert cap_for_utilisation(65.0) == 2

    def test_third_step(self) -> None:
        assert cap_for_utilisation(75.0) == 1

    def test_at_threshold_returns_none(self) -> None:
        assert cap_for_utilisation(80.0) is None

    def test_above_threshold_returns_none(self) -> None:
        assert cap_for_utilisation(95.0) is None

    def test_custom_threshold(self) -> None:
        assert cap_for_utilisation(70.0, threshold_percent=70) is None

    def test_full_step_sequence(self) -> None:
        assert cap_for_utilisation(0.0) == 3
        assert cap_for_utilisation(49.9) == 3
        assert cap_for_utilisation(50.0) == 3
        assert cap_for_utilisation(64.9) == 3
        assert cap_for_utilisation(65.0) == 2
        assert cap_for_utilisation(74.9) == 2
        assert cap_for_utilisation(75.0) == 1
        assert cap_for_utilisation(79.9) == 1
        assert cap_for_utilisation(80.0) is None


class TestApplyCapStep:
    def test_low_utilisation_no_change(self) -> None:
        scheduler = WaveScheduler(cap=3)
        result = apply_cap_step(scheduler, _snapshot(30.0))
        assert result.new_cap == 3
        assert result.paused is False
        assert scheduler.cap == 3

    def test_step_to_two(self) -> None:
        scheduler = WaveScheduler(cap=3)
        result = apply_cap_step(scheduler, _snapshot(65.0))
        assert result.previous_cap == 3
        assert result.new_cap == 2
        assert result.paused is False
        assert scheduler.cap == 2

    def test_step_to_one(self) -> None:
        scheduler = WaveScheduler(cap=3)
        result = apply_cap_step(scheduler, _snapshot(75.0))
        assert result.new_cap == 1
        assert scheduler.cap == 1

    def test_pause_at_threshold(self) -> None:
        scheduler = WaveScheduler(cap=3)
        result = apply_cap_step(scheduler, _snapshot(85.0))
        assert result.new_cap == 0
        assert result.paused is True
        assert scheduler.is_paused is True

    def test_gradual_step_down(self) -> None:
        scheduler = WaveScheduler(cap=3)

        apply_cap_step(scheduler, _snapshot(50.0))
        assert scheduler.cap == 3

        apply_cap_step(scheduler, _snapshot(65.0))
        assert scheduler.cap == 2

        apply_cap_step(scheduler, _snapshot(75.0))
        assert scheduler.cap == 1

        result = apply_cap_step(scheduler, _snapshot(80.0))
        assert result.paused is True
        assert scheduler.is_paused is True

    def test_does_not_step_up(self) -> None:
        scheduler = WaveScheduler(cap=1)
        result = apply_cap_step(scheduler, _snapshot(30.0))
        assert result.new_cap == 3
        assert scheduler.cap == 1

    def test_empty_snapshot_no_change(self) -> None:
        scheduler = WaveScheduler(cap=3)
        snap = UsageSnapshot(meters=[], provider="claude", plan="pro", timestamp=1.0)
        result = apply_cap_step(scheduler, snap)
        assert result.new_cap == 3
        assert result.paused is False

    def test_hand_off_to_hard_pause(self) -> None:
        scheduler = WaveScheduler(cap=1)
        result = apply_cap_step(scheduler, _snapshot(82.0))
        assert result.paused is True
        assert scheduler.is_paused is True
        assert result.previous_cap == 1
        assert result.new_cap == 0
