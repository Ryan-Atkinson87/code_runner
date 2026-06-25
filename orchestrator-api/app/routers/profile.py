from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_auth
from app.engine.profile_generation import (
    ProfileGenerationResult,
    ProfileProposal,
    ProposalOutcome,
    confirm_and_write,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

router = APIRouter(
    prefix="/profile",
    tags=["profile"],
    dependencies=[Depends(require_auth)],
)

_generate_fn: Callable[..., Awaitable[ProfileGenerationResult]] | None = None
_output_path: Path = Path("execution-profile.yaml")
_pending_proposal: ProfileProposal | None = None


def init_profile_deps(
    generate_fn: Callable[..., Awaitable[ProfileGenerationResult]],
    output_path: Path,
) -> None:
    global _generate_fn, _output_path
    _generate_fn = generate_fn
    _output_path = output_path


class ProposalResponse(BaseModel):
    outcome: str
    raw_yaml: str = ""
    error: str = ""


class ConfirmResponse(BaseModel):
    written: bool
    path: str = ""


@router.post("/propose", response_model=ProposalResponse)
async def propose_profile() -> ProposalResponse:
    global _pending_proposal

    if _generate_fn is None:
        raise RuntimeError("Profile generation not initialised")

    result = await _generate_fn()

    if result.outcome != ProposalOutcome.PROPOSED or result.proposal is None:
        _pending_proposal = None
        return ProposalResponse(
            outcome=result.outcome,
            error=result.error,
        )

    _pending_proposal = result.proposal
    return ProposalResponse(
        outcome=result.outcome,
        raw_yaml=result.proposal.raw_yaml,
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_profile() -> ConfirmResponse:
    global _pending_proposal

    if _pending_proposal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending proposal to confirm",
        )

    path = confirm_and_write(_pending_proposal, _output_path)
    _pending_proposal = None
    return ConfirmResponse(written=True, path=str(path))


@router.post("/reject", response_model=ConfirmResponse)
async def reject_profile() -> ConfirmResponse:
    global _pending_proposal
    _pending_proposal = None
    return ConfirmResponse(written=False)
