from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.usage.policy import PolicyAction, UsagePolicy, _in_peak_window


def _pacific_ts(year: int, month: int, day: int, hour: int) -> float:
    """Create a timestamp for a specific Pacific time."""
    pacific = ZoneInfo("America/Los_Angeles")
    dt = datetime(year, month, day, hour, 0, 0, tzinfo=pacific)
    return dt.timestamp()


# Wednesday 2026-06-24 at 8am Pacific = inside peak window
_INSIDE_PEAK = _pacific_ts(2026, 6, 24, 8)
# Wednesday 2026-06-24 at 2pm Pacific = outside peak window
_OUTSIDE_PEAK = _pacific_ts(2026, 6, 24, 14)
# Saturday 2026-06-27 at 8am Pacific = weekend, outside peak
_WEEKEND_MORNING = _pacific_ts(2026, 6, 27, 8)


class TestInPeakWindow:
    def test_weekday_morning_is_peak(self) -> None:
        assert _in_peak_window(_INSIDE_PEAK) is True

    def test_weekday_afternoon_not_peak(self) -> None:
        assert _in_peak_window(_OUTSIDE_PEAK) is False

    def test_weekend_morning_not_peak(self) -> None:
        assert _in_peak_window(_WEEKEND_MORNING) is False

    def test_edge_start(self) -> None:
        at_5am = _pacific_ts(2026, 6, 24, 5)
        assert _in_peak_window(at_5am) is True

    def test_edge_end(self) -> None:
        at_11am = _pacific_ts(2026, 6, 24, 11)
        assert _in_peak_window(at_11am) is False

    def test_just_before_peak(self) -> None:
        at_4am = _pacific_ts(2026, 6, 24, 4)
        assert _in_peak_window(at_4am) is False


class TestOverride:
    def test_override_suppresses_pause(self) -> None:
        policy = UsagePolicy()
        policy.set_override(True)
        assert policy.evaluate(threshold_reached=True) == PolicyAction.PROCEED

    def test_override_suppresses_throttle(self) -> None:
        policy = UsagePolicy()
        policy.set_override(True)
        result = policy.evaluate(threshold_reached=False, now=_INSIDE_PEAK)
        assert result == PolicyAction.PROCEED

    def test_override_is_explicit(self) -> None:
        policy = UsagePolicy()
        assert policy.override_active is False
        policy.set_override(True)
        assert policy.override_active is True

    def test_override_clears_on_new_run(self) -> None:
        policy = UsagePolicy()
        policy.set_override(True)
        policy.clear_for_new_run()
        assert policy.override_active is False

    def test_override_persists_when_configured(self) -> None:
        policy = UsagePolicy()
        policy.set_override(True)
        policy.set_persist_override(True)
        policy.clear_for_new_run()
        assert policy.override_active is True


class TestPeakHourThrottle:
    def test_throttle_in_peak_window(self) -> None:
        policy = UsagePolicy(peak_hour_throttle_enabled=True)
        result = policy.evaluate(threshold_reached=False, now=_INSIDE_PEAK)
        assert result == PolicyAction.THROTTLE

    def test_no_throttle_outside_peak(self) -> None:
        policy = UsagePolicy(peak_hour_throttle_enabled=True)
        result = policy.evaluate(threshold_reached=False, now=_OUTSIDE_PEAK)
        assert result == PolicyAction.PROCEED

    def test_throttle_disabled_by_config(self) -> None:
        policy = UsagePolicy(peak_hour_throttle_enabled=False)
        result = policy.evaluate(threshold_reached=False, now=_INSIDE_PEAK)
        assert result == PolicyAction.PROCEED

    def test_pause_takes_precedence_over_throttle(self) -> None:
        policy = UsagePolicy(peak_hour_throttle_enabled=True)
        result = policy.evaluate(threshold_reached=True, now=_INSIDE_PEAK)
        assert result == PolicyAction.PAUSE


class TestPolicyState:
    def test_state_reflects_override(self) -> None:
        policy = UsagePolicy()
        policy.set_override(True)
        state = policy.state()
        assert state.override_active is True
        assert state.peak_throttle_active is False

    def test_state_reflects_peak_window(self) -> None:
        policy = UsagePolicy()
        state = policy.state(now=_INSIDE_PEAK)
        assert state.in_peak_window is True
        assert state.peak_throttle_active is True

    def test_state_outside_peak(self) -> None:
        policy = UsagePolicy()
        state = policy.state(now=_OUTSIDE_PEAK)
        assert state.in_peak_window is False


class TestComposition:
    def test_normal_flow_proceed(self) -> None:
        policy = UsagePolicy()
        result = policy.evaluate(threshold_reached=False, now=_OUTSIDE_PEAK)
        assert result == PolicyAction.PROCEED

    def test_threshold_reached_pauses(self) -> None:
        policy = UsagePolicy()
        result = policy.evaluate(threshold_reached=True, now=_OUTSIDE_PEAK)
        assert result == PolicyAction.PAUSE

    def test_override_beats_everything(self) -> None:
        policy = UsagePolicy(peak_hour_throttle_enabled=True)
        policy.set_override(True)
        result = policy.evaluate(threshold_reached=True, now=_INSIDE_PEAK)
        assert result == PolicyAction.PROCEED
