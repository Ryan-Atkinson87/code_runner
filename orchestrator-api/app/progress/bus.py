from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    """A single progress update emitted by the engine."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)


class ProgressBus:
    """Async pub/sub bus that bridges the engine and SSE subscribers.

    One bus per process. The engine calls publish() at key boundaries;
    each connected SSE client has a subscriber queue. Slow clients
    receive dropped events rather than blocking the engine; a queue
    that fills is silently trimmed.

    None sentinel in a queue signals stream end — client should close.
    """

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[ProgressEvent | None]] = []
        self._last_run_state: ProgressEvent | None = None

    def subscribe(self) -> asyncio.Queue[ProgressEvent | None]:
        """Open a subscription queue. Replays the last run_state immediately."""
        q: asyncio.Queue[ProgressEvent | None] = asyncio.Queue(maxsize=512)
        self._queues.append(q)
        if self._last_run_state is not None:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(self._last_run_state)
        return q

    def unsubscribe(self, q: asyncio.Queue[ProgressEvent | None]) -> None:
        with contextlib.suppress(ValueError):
            self._queues.remove(q)

    def publish(self, event: ProgressEvent) -> None:
        """Publish an event to all current subscribers."""
        if event.event_type == "run_state":
            self._last_run_state = event
        for q in list(self._queues):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    def close_all(self) -> None:
        """Signal end-of-stream to all subscribers and clear run state."""
        self._last_run_state = None
        for q in list(self._queues):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)
