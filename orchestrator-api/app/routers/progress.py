from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth.dependencies import require_auth
from app.progress.bus import ProgressBus

router = APIRouter(prefix="/runs", tags=["progress"])

_bus: ProgressBus | None = None

_HEARTBEAT_INTERVAL = 15.0


def init_progress_bus(bus: ProgressBus) -> None:
    global _bus
    _bus = bus


def _get_bus() -> ProgressBus:
    if _bus is None:
        raise RuntimeError("ProgressBus not initialised")
    return _bus


@router.get("/{run_id}/progress")
async def stream_progress(
    run_id: int,
    _session: str = Depends(require_auth),
) -> StreamingResponse:
    """Stream live progress events for a run as Server-Sent Events.

    Each SSE frame carries an ``event:`` type and a JSON ``data:`` payload.
    A ``: keepalive`` comment is sent every 15 s while the run is active.
    The stream closes with a ``run_ended`` event when the run finishes.
    """
    bus = _get_bus()
    return StreamingResponse(
        content=_event_stream(bus, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _event_stream(bus: ProgressBus, run_id: int) -> AsyncIterator[str]:
    q = bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_INTERVAL)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue

            if event is None:
                yield "event: run_ended\ndata: {}\n\n"
                break

            yield f"event: {event.event_type}\ndata: {json.dumps(event.data)}\n\n"
    finally:
        bus.unsubscribe(q)
