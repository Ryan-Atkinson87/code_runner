from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.blockers.models import Blocker
from app.blockers.store import BlockerStore, BlockerStoreError

router = APIRouter(prefix="/blockers", tags=["blockers"], dependencies=[Depends(require_auth)])

_store: BlockerStore | None = None


def _default_run_id_fn() -> None:
    return None


_run_id_fn: Callable[[], int | None] = _default_run_id_fn


def init_blockers_deps(
    store: BlockerStore,
    run_id_fn: Callable[[], int | None],
) -> None:
    global _store, _run_id_fn
    _store = store
    _run_id_fn = run_id_fn


def _get_store() -> BlockerStore:
    if _store is None:
        raise RuntimeError("BlockerStore not initialised")
    return _store


def _get_run_id() -> int:
    run_id = _run_id_fn()
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active run",
        )
    return run_id


class BlockerResponse(BaseModel):
    id: int | None = None
    run_id: int
    issue_number: int
    blocker_type: str
    reason: str
    needed_to_unblock: str
    status: str
    created_at: str = ""
    resolved_at: str | None = None
    resolution_response: str | None = None


class BlockerListResponse(BaseModel):
    blockers: list[BlockerResponse]
    run_id: int


class ResolveRequest(BaseModel):
    response: str = Field(min_length=1)


def _to_response(b: Blocker) -> BlockerResponse:
    return BlockerResponse(
        id=b.id,
        run_id=b.run_id,
        issue_number=b.issue_number,
        blocker_type=b.blocker_type.value,
        reason=b.reason,
        needed_to_unblock=b.needed_to_unblock,
        status=b.status.value,
        created_at=b.created_at,
        resolved_at=b.resolved_at,
        resolution_response=b.resolution_response,
    )


@router.get("", response_model=BlockerListResponse)
async def list_blockers() -> BlockerListResponse:
    store = _get_store()
    run_id = _get_run_id()
    blockers = store.list_parked(run_id)
    return BlockerListResponse(
        blockers=[_to_response(b) for b in blockers],
        run_id=run_id,
    )


@router.post(
    "/{issue_number}/resolve",
    response_model=BlockerResponse,
)
async def resolve_blocker(issue_number: int, body: ResolveRequest) -> BlockerResponse:
    store = _get_store()
    run_id = _get_run_id()
    try:
        resolved = store.resolve(run_id, issue_number, resolution_response=body.response)
    except BlockerStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _to_response(resolved)
