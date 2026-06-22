from __future__ import annotations

import logging
from dataclasses import dataclass

from app.engine.scheduler import WaveScheduler
from app.usage.models import UsageSnapshot, governing_meter

logger = logging.getLogger(__name__)

_DEFAULT_STEPS: list[tuple[float, int]] = [
    (50.0, 3),
    (65.0, 2),
    (75.0, 1),
]


@dataclass(frozen=True, slots=True)
class CapStepResult:
    previous_cap: int
    new_cap: int
    governing_utilisation: float
    paused: bool


def cap_for_utilisation(
    utilisation: float,
    threshold_percent: int = 80,
    steps: list[tuple[float, int]] | None = None,
) -> int | None:
    """Map governing-meter utilisation to a concurrency cap.

    Returns None when utilisation >= threshold (hand-off to hard pause).
    Steps are (utilisation_floor, cap) pairs in ascending order.
    Below the first step, no cap reduction is applied (returns the
    highest cap value).
    """
    if utilisation >= threshold_percent:
        return None

    step_list = steps if steps is not None else _DEFAULT_STEPS
    cap = step_list[0][1] if step_list else 3

    for floor, step_cap in step_list:
        if utilisation >= floor:
            cap = step_cap
        else:
            break

    return cap


def apply_cap_step(
    scheduler: WaveScheduler,
    snapshot: UsageSnapshot,
    threshold_percent: int = 80,
) -> CapStepResult:
    """Evaluate the current snapshot and step the scheduler's cap.

    Driven by the same ~5-min poll as the threshold check. Does not
    interrupt already-running sessions — only lowers the ceiling for
    the next scheduling decision.
    """
    gov = governing_meter(snapshot)
    if gov is None:
        return CapStepResult(
            previous_cap=scheduler.cap,
            new_cap=scheduler.cap,
            governing_utilisation=0.0,
            paused=False,
        )

    previous_cap = scheduler.cap
    target = cap_for_utilisation(gov.utilisation, threshold_percent)

    if target is None:
        scheduler.pause()
        logger.info(
            "Cap step: %.1f%% >= %d%% threshold — pausing (was cap=%d)",
            gov.utilisation,
            threshold_percent,
            previous_cap,
        )
        return CapStepResult(
            previous_cap=previous_cap,
            new_cap=0,
            governing_utilisation=gov.utilisation,
            paused=True,
        )

    if target < previous_cap:
        scheduler.step_down_cap(target)
        logger.info(
            "Cap step: %.1f%% utilisation — cap %d → %d",
            gov.utilisation,
            previous_cap,
            target,
        )

    return CapStepResult(
        previous_cap=previous_cap,
        new_cap=target,
        governing_utilisation=gov.utilisation,
        paused=False,
    )
