from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SessionRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    IMPLEMENTOR = "implementor"


class SessionOutcome(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ERROR = "error"


class EventKind(StrEnum):
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    OUTPUT = "output"


class NormalisedEvent(BaseModel):
    """Provider-neutral event suitable for SSE streaming to the UI.

    Maps the four event kinds from Spec §3.1 into a single shape that
    lets the UI render live progress identically regardless of provider.
    """

    kind: EventKind
    content: str = ""
    tool_name: str | None = None
    tool_input: str | None = None
    timestamp: float = Field(default=0.0)


class UsageReport(BaseModel):
    """Token and cost accounting for a single provider session."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    duration_seconds: float = 0.0


class SessionResult(BaseModel):
    """Result of a single provider session (Spec §3.1).

    Each call is a fresh, stateless session (§4.3). ``artifacts`` lists
    files changed as derived from git diff, not provider self-report.
    """

    events: list[NormalisedEvent] = Field(default_factory=list)
    usage: UsageReport = Field(default_factory=UsageReport)
    outcome: SessionOutcome
    artifacts: list[str] = Field(default_factory=list)


ProviderName = Literal["claude", "codex", "gemini"]
