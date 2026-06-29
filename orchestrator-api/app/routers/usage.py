from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.usage.monitor import UsageMonitor
from app.usage.policy import UsagePolicy

router = APIRouter(prefix="/usage", tags=["usage"], dependencies=[Depends(require_auth)])

_monitor: UsageMonitor | None = None
_policy: UsagePolicy | None = None


def init_usage_deps(
    monitor: UsageMonitor,
    policy: UsagePolicy,
) -> None:
    global _monitor, _policy
    _monitor = monitor
    _policy = policy


def _get_monitor() -> UsageMonitor:
    if _monitor is None:
        raise RuntimeError("UsageMonitor not initialised")
    return _monitor


def _get_policy() -> UsagePolicy:
    if _policy is None:
        raise RuntimeError("UsagePolicy not initialised")
    return _policy


class MeterResponse(BaseModel):
    kind: str
    utilisation: float
    resets_at: float | None = None
    limit: float | None = None
    used: float | None = None
    is_governing: bool = False


class UsageGaugesResponse(BaseModel):
    meters: list[MeterResponse] = Field(default_factory=list)
    threshold_percent: int = 80
    threshold_reached: bool = False
    override_active: bool = False
    provider: str = ""
    plan: str = ""


class OverrideRequest(BaseModel):
    active: bool


class OverrideResponse(BaseModel):
    override_active: bool


@router.get("/gauges", response_model=UsageGaugesResponse)
async def get_gauges() -> UsageGaugesResponse:
    monitor = _get_monitor()
    state = monitor.state

    if state is None or state.snapshot is None:
        policy = _get_policy()
        return UsageGaugesResponse(
            override_active=policy.override_active,
        )

    governing = state.governing
    governing_kind = governing.kind if governing is not None else None

    meters = [
        MeterResponse(
            kind=m.kind,
            utilisation=m.utilisation,
            resets_at=m.resets_at,
            limit=m.limit,
            used=m.used,
            is_governing=(m.kind == governing_kind),
        )
        for m in state.snapshot.meters
    ]

    threshold_reached = state.threshold.reached if state.threshold is not None else False

    return UsageGaugesResponse(
        meters=meters,
        threshold_percent=(
            state.threshold.threshold_percent if state.threshold is not None else 80
        ),
        threshold_reached=threshold_reached,
        override_active=state.policy_state.override_active,
        provider=state.snapshot.provider,
        plan=state.snapshot.plan,
    )


@router.post("/override", response_model=OverrideResponse)
async def set_override(body: OverrideRequest) -> OverrideResponse:
    policy = _get_policy()
    policy.set_override(body.active)
    return OverrideResponse(override_active=policy.override_active)
