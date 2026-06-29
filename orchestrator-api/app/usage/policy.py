from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

_PACIFIC = ZoneInfo("America/Los_Angeles")
_PEAK_START_HOUR = 5
_PEAK_END_HOUR = 11
_PEAK_WEEKDAYS = frozenset(range(5))  # Monday=0 .. Friday=4


class PolicyAction(StrEnum):
    PROCEED = "proceed"
    THROTTLE = "throttle"
    PAUSE = "pause"


@dataclass(slots=True)
class UsagePolicyState:
    """Observable state of the two policy modifiers."""

    override_active: bool = False
    peak_throttle_active: bool = False
    in_peak_window: bool = False


@dataclass(slots=True)
class UsagePolicy:
    """Override switch and peak-hour throttle (Spec §6.5, §6.7).

    Sits on top of the threshold/cap-step/pause chain and modifies
    the gating decision. Override suppresses everything; peak-hour
    throttle defers heavy work during the burn window.
    """

    peak_hour_throttle_enabled: bool = True
    _override: bool = field(default=False, repr=False)
    _run_scoped: bool = field(default=True, repr=False)

    @property
    def override_active(self) -> bool:
        return self._override

    def set_override(self, active: bool) -> None:
        self._override = active

    def clear_for_new_run(self) -> None:
        """Clear override at run start unless deliberately left on."""
        if self._run_scoped:
            self._override = False

    def set_persist_override(self, persist: bool) -> None:
        self._run_scoped = not persist

    def evaluate(
        self,
        threshold_reached: bool,
        *,
        now: float | None = None,
    ) -> PolicyAction:
        """Apply policy modifiers to the gating decision.

        Override short-circuits everything. Peak-hour throttle defers
        rather than pauses.
        """
        if self._override:
            return PolicyAction.PROCEED

        if threshold_reached:
            return PolicyAction.PAUSE

        if self.peak_hour_throttle_enabled and _in_peak_window(now):
            return PolicyAction.THROTTLE

        return PolicyAction.PROCEED

    def state(self, *, now: float | None = None) -> UsagePolicyState:
        return UsagePolicyState(
            override_active=self._override,
            peak_throttle_active=(self.peak_hour_throttle_enabled and not self._override),
            in_peak_window=_in_peak_window(now),
        )


def _in_peak_window(now: float | None = None) -> bool:
    ts = now if now is not None else time.time()
    dt = datetime.fromtimestamp(ts, tz=UTC).astimezone(_PACIFIC)
    if dt.weekday() not in _PEAK_WEEKDAYS:
        return False
    return _PEAK_START_HOUR <= dt.hour < _PEAK_END_HOUR
