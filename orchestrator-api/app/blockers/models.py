from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class BlockerType(Enum):
    MISSING_SPEC = "missing_spec"
    CONTRACT_CONFLICT = "contract_conflict"
    UNMET_DEPENDENCY = "unmet_dependency"
    STUCK_AGENT = "stuck_agent"
    OTHER = "other"


class BlockerStatus(Enum):
    PARKED = "parked"
    RESOLVED = "resolved"


class Blocker(BaseModel):
    id: int | None = None
    run_id: int
    issue_number: int
    blocker_type: BlockerType
    reason: str
    needed_to_unblock: str
    status: BlockerStatus = BlockerStatus.PARKED
    created_at: str = ""
    resolved_at: str | None = None
    resolution_response: str | None = None
