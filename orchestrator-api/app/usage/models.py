from __future__ import annotations

import time

from pydantic import BaseModel, Field

from app.providers.types import ProviderName


class MeterKind:
    """Known meter kinds (Spec §6.1).

    Meter.kind is a plain str so unknown kinds from the source pass
    through without code changes (§6.2 volatility caveat).
    """

    FIVE_HOUR = "five_hour"
    SEVEN_DAY = "seven_day"
    SEVEN_DAY_OPUS = "seven_day_opus"
    SEVEN_DAY_SONNET = "seven_day_sonnet"
    AGENT_SDK_CREDIT = "agent_sdk_credit"
    API_BUDGET = "api_budget"


class Meter(BaseModel):
    """A single usage meter (Spec §6.1)."""

    kind: str
    utilisation: float = Field(ge=0.0)
    resets_at: float | None = None
    limit: float | None = None
    used: float | None = None


class UsageSnapshot(BaseModel):
    """Aggregate of all meters for the active provider/plan at a point in time."""

    meters: list[Meter] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)
    provider: ProviderName
    plan: str


_SUBSCRIPTION_METERS: frozenset[str] = frozenset(
    {
        MeterKind.FIVE_HOUR,
        MeterKind.SEVEN_DAY,
        MeterKind.SEVEN_DAY_OPUS,
        MeterKind.SEVEN_DAY_SONNET,
        MeterKind.AGENT_SDK_CREDIT,
    }
)

_API_METERS: frozenset[str] = frozenset(
    {
        MeterKind.API_BUDGET,
    }
)

_PLAN_METER_MAP: dict[tuple[ProviderName, str], frozenset[str]] = {
    ("claude", "pro"): _SUBSCRIPTION_METERS,
    ("claude", "max"): _SUBSCRIPTION_METERS,
    ("claude", "api"): _API_METERS,
}


def applicable_meters(provider: ProviderName, plan: str) -> frozenset[str]:
    """Return meter kinds that apply to a provider/plan combo.

    Returns an empty set for unknown combos rather than crashing (§6.2).
    """
    return _PLAN_METER_MAP.get((provider, plan), frozenset())


def governing_meter(snapshot: UsageSnapshot) -> Meter | None:
    """Return the most restrictive meter (highest utilisation).

    Ties broken by kind name (ascending alphabetical) for determinism.
    Returns None if the snapshot has no meters.
    """
    if not snapshot.meters:
        return None
    return max(snapshot.meters, key=lambda m: (m.utilisation, m.kind))
