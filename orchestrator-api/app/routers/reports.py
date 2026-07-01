from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.observability.reports import EfficiencyReport, EfficiencyReportGenerator
from app.observability.rollup import RollupStore

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_auth)])

_rollup_store: RollupStore | None = None
_generator: EfficiencyReportGenerator = EfficiencyReportGenerator()


def init_reports_deps(rollup_store: RollupStore) -> None:
    global _rollup_store
    _rollup_store = rollup_store


def _get_store() -> RollupStore:
    if _rollup_store is None:
        raise RuntimeError("RollupStore not initialised for reports router")
    return _rollup_store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TokenBreakdownResponse(BaseModel):
    by_issue: dict[int, int] = Field(default_factory=dict)
    by_role: dict[str, int] = Field(default_factory=dict)
    by_skill: dict[str, int] = Field(default_factory=dict)
    by_wave: dict[str, int] = Field(default_factory=dict)
    total_in: int = 0
    total_out: int = 0


class RetryStatsResponse(BaseModel):
    total_retries: int = 0
    avg_per_session: float = 0.0
    high_retry_skills: list[str] = Field(default_factory=list)


class ModelOutcomeResponse(BaseModel):
    model: str
    session_count: int
    completed_count: int
    blocked_count: int
    error_count: int
    total_tokens: int
    total_cost_usd: float
    completion_rate: float


class RegressionFlagResponse(BaseModel):
    metric: str
    earlier_month: str
    later_month: str
    earlier_value: float
    later_value: float
    pct_increase: float


class SuggestionResponse(BaseModel):
    category: str
    message: str


class EfficiencyReportResponse(BaseModel):
    scope: str
    generated_at: datetime
    total_sessions: int = 0
    total_cost_usd: float = 0.0
    tokens: TokenBreakdownResponse = Field(default_factory=TokenBreakdownResponse)
    retries: RetryStatsResponse = Field(default_factory=RetryStatsResponse)
    model_outcomes: list[ModelOutcomeResponse] = Field(default_factory=list)
    regressions: list[RegressionFlagResponse] = Field(default_factory=list)
    suggestions: list[SuggestionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _serialise(report: EfficiencyReport) -> EfficiencyReportResponse:
    return EfficiencyReportResponse(
        scope=report.scope,
        generated_at=report.generated_at,
        total_sessions=report.total_sessions,
        total_cost_usd=report.total_cost_usd,
        tokens=TokenBreakdownResponse(
            by_issue=report.tokens.by_issue,
            by_role=report.tokens.by_role,
            by_skill=report.tokens.by_skill,
            by_wave=report.tokens.by_wave,
            total_in=report.tokens.total_in,
            total_out=report.tokens.total_out,
        ),
        retries=RetryStatsResponse(
            total_retries=report.retries.total_retries,
            avg_per_session=report.retries.avg_per_session,
            high_retry_skills=report.retries.high_retry_skills,
        ),
        model_outcomes=[
            ModelOutcomeResponse(
                model=mo.model,
                session_count=mo.session_count,
                completed_count=mo.completed_count,
                blocked_count=mo.blocked_count,
                error_count=mo.error_count,
                total_tokens=mo.total_tokens,
                total_cost_usd=mo.total_cost_usd,
                completion_rate=mo.completion_rate,
            )
            for mo in report.model_outcomes
        ],
        regressions=[
            RegressionFlagResponse(
                metric=rf.metric,
                earlier_month=rf.earlier_month,
                later_month=rf.later_month,
                earlier_value=rf.earlier_value,
                later_value=rf.later_value,
                pct_increase=rf.pct_increase,
            )
            for rf in report.regressions
        ],
        suggestions=[
            SuggestionResponse(category=s.category, message=s.message) for s in report.suggestions
        ],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=EfficiencyReportResponse)
async def get_on_demand_report() -> EfficiencyReportResponse:
    store = _get_store()
    try:
        report = _generator.generate_on_demand(store)
    except Exception as exc:
        _log.error("Failed to generate on-demand report: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation failed",
        ) from exc
    return _serialise(report)


@router.get("/wave/{wave}", response_model=EfficiencyReportResponse)
async def get_wave_report(wave: str) -> EfficiencyReportResponse:
    store = _get_store()
    try:
        report = _generator.generate_for_wave(store, wave)
    except Exception as exc:
        _log.error("Failed to generate wave report for %r: %s", wave, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation failed",
        ) from exc
    return _serialise(report)


@router.get("/month/{month}", response_model=EfficiencyReportResponse)
async def get_month_report(month: str) -> EfficiencyReportResponse:
    store = _get_store()
    try:
        report = _generator.generate_for_month(store, month)
    except Exception as exc:
        _log.error("Failed to generate month report for %r: %s", month, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation failed",
        ) from exc
    return _serialise(report)
