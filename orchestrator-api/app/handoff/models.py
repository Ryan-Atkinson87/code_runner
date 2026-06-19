from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IssueNote:
    number: int
    summary: str


@dataclass(frozen=True)
class ParkedBlocker:
    issue_number: int
    reason: str


@dataclass(frozen=True)
class HandoffInput:
    wave_name: str
    summary: str
    issue_notes: list[IssueNote] = field(default_factory=list)
    engine_checks: list[str] = field(default_factory=list)
    human_checks: list[str] = field(default_factory=list)
    parked_blockers: list[ParkedBlocker] = field(default_factory=list)
