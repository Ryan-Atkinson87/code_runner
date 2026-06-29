from __future__ import annotations

import time
from dataclasses import dataclass

from app.usage.models import Meter, MeterKind, UsageSnapshot, governing_meter

_SDK_CREDIT_CUTOVER = 1750003200.0  # 2026-06-15T00:00:00 UTC

_SDK_CREDIT_KINDS: frozenset[str] = frozenset({MeterKind.AGENT_SDK_CREDIT})
_CHAT_POOL_KINDS: frozenset[str] = frozenset(
    {
        MeterKind.FIVE_HOUR,
        MeterKind.SEVEN_DAY,
        MeterKind.SEVEN_DAY_OPUS,
        MeterKind.SEVEN_DAY_SONNET,
    }
)


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """Result of evaluating usage against the pause threshold."""

    reached: bool
    governing: Meter | None
    threshold_percent: int


def evaluate_threshold(
    snapshot: UsageSnapshot,
    threshold_percent: int = 80,
    *,
    now: float | None = None,
) -> ThresholdResult:
    """Check whether the governing meter has reached the pause threshold.

    Spec §6.3: pause at threshold_percent of the most restrictive meter.
    No model downgrade — only reached/not-reached.
    """
    gov = governing_meter(snapshot)
    if gov is None:
        return ThresholdResult(reached=False, governing=None, threshold_percent=threshold_percent)

    reached = gov.utilisation >= threshold_percent
    return ThresholdResult(reached=reached, governing=gov, threshold_percent=threshold_percent)


def human_reserve_meter(
    snapshot: UsageSnapshot,
    *,
    now: float | None = None,
) -> str:
    """Return the meter kind to watch for "reserve capacity for the human".

    Before the SDK credit cutover (2026-06-15), agent and human share the
    chat pool — reserve against the chat-pool meters. After the cutover,
    SDK usage has its own monthly credit — reserve against that instead.
    """
    ts = now if now is not None else time.time()
    if ts >= _SDK_CREDIT_CUTOVER:
        return MeterKind.AGENT_SDK_CREDIT
    for m in snapshot.meters:
        if m.kind in _CHAT_POOL_KINDS:
            return m.kind
    return MeterKind.FIVE_HOUR
