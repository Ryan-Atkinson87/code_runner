from __future__ import annotations

import logging
from dataclasses import dataclass

from app.engine.scheduler import WaveScheduler
from app.providers.types import ProviderName
from app.usage.cap_stepper import CapStepResult, apply_cap_step
from app.usage.models import Meter, UsageSnapshot, applicable_meters, governing_meter
from app.usage.pause import UsagePauseManager
from app.usage.policy import PolicyAction, UsagePolicy, UsagePolicyState
from app.usage.reader import UsageReader
from app.usage.threshold import ThresholdResult, evaluate_threshold

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MonitorState:
    """Full observable state of the usage monitor for the UI."""

    snapshot: UsageSnapshot | None
    threshold: ThresholdResult | None
    cap_step: CapStepResult | None
    policy_action: PolicyAction
    policy_state: UsagePolicyState
    governing: Meter | None
    applicable_meter_kinds: frozenset[str]


@dataclass(slots=True)
class MonitorCheckResult:
    """Result of a single monitor cycle."""

    action: PolicyAction
    state: MonitorState
    error: str | None = None


class UsageMonitor:
    """Assembled usage monitor (Spec §6).

    Wires reader -> threshold -> cap-step -> policy -> pause/resume
    into a single check() method the wave loop calls each poll cycle.
    """

    def __init__(
        self,
        reader: UsageReader,
        policy: UsagePolicy,
        scheduler: WaveScheduler,
        pause_manager: UsagePauseManager | None = None,
        threshold_percent: int = 80,
        provider: ProviderName = "claude",
        plan: str = "pro",
    ) -> None:
        self._reader = reader
        self._policy = policy
        self._scheduler = scheduler
        self._pause_manager = pause_manager
        self._threshold_percent = threshold_percent
        self._provider: ProviderName = provider
        self._plan = plan
        self._last_state: MonitorState | None = None

    async def check(self, run_id: int = 0) -> MonitorCheckResult:
        """Run one monitor cycle: read -> evaluate -> act."""
        try:
            snapshot = await self._reader.read()
        except Exception as exc:
            logger.warning("Usage read failed: %s", exc)
            return MonitorCheckResult(
                action=PolicyAction.PROCEED,
                state=self._empty_state(),
                error=str(exc),
            )

        threshold_result = evaluate_threshold(
            snapshot, self._threshold_percent
        )
        cap_result = apply_cap_step(
            self._scheduler, snapshot, self._threshold_percent
        )
        action = self._policy.evaluate(
            threshold_reached=threshold_result.reached
        )

        if action == PolicyAction.PAUSE and self._pause_manager and run_id:
            gov = governing_meter(snapshot)
            if gov and not self._pause_manager.is_paused(run_id):
                self._pause_manager.set_paused(run_id, gov)

        state = MonitorState(
            snapshot=snapshot,
            threshold=threshold_result,
            cap_step=cap_result,
            policy_action=action,
            policy_state=self._policy.state(),
            governing=governing_meter(snapshot),
            applicable_meter_kinds=applicable_meters(self._provider, self._plan),
        )
        self._last_state = state
        return MonitorCheckResult(action=action, state=state)

    def switch_reader(
        self,
        new_reader: UsageReader,
        provider: ProviderName,
        plan: str,
    ) -> None:
        """Handle a provider/plan switch (Spec §6.8).

        Reloads the reader and meter set. No restart required.
        """
        self._reader = new_reader
        self._provider = provider
        self._plan = plan
        logger.info("Monitor switched to %s/%s", provider, plan)

    @property
    def state(self) -> MonitorState | None:
        return self._last_state

    @property
    def policy(self) -> UsagePolicy:
        return self._policy

    def _empty_state(self) -> MonitorState:
        return MonitorState(
            snapshot=None,
            threshold=None,
            cap_step=None,
            policy_action=PolicyAction.PROCEED,
            policy_state=self._policy.state(),
            governing=None,
            applicable_meter_kinds=applicable_meters(self._provider, self._plan),
        )
