from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.providers.types import (
    AuditRecord,
    NormalisedEvent,
    SessionOutcome,
    SessionRole,
    UsageReport,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SessionCapture(BaseModel):
    """Layer 1 raw capture record for a single AI session (Spec §11.1).

    Contains the full event stream plus aggregation keys so Layer 2 and
    rollups can slice by issue, role, skill/step, wave, and month.
    """

    session_id: str
    run_id: int
    wave: str
    issue_number: int
    role: SessionRole
    skill: str
    model: str

    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime = Field(default_factory=_utcnow)

    events: list[NormalisedEvent] = Field(default_factory=list)
    usage: UsageReport = Field(default_factory=UsageReport)
    audit_log: list[AuditRecord] = Field(default_factory=list)
    outcome: SessionOutcome
    artifacts: list[str] = Field(default_factory=list)

    retry_count: int = 0
