from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from app.progress.bus import ProgressBus, ProgressEvent

if TYPE_CHECKING:
    from fastapi import FastAPI


class TestProgressBusPublishSubscribe:
    @pytest.mark.asyncio
    async def test_subscriber_receives_published_event(self) -> None:
        bus = ProgressBus()
        q = bus.subscribe()
        event = ProgressEvent(event_type="run_state", data={"run_id": 1, "status": "running"})
        bus.publish(event)
        received = q.get_nowait()
        assert received is not None
        assert received.event_type == "run_state"
        assert received.data["status"] == "running"

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self) -> None:
        bus = ProgressBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish(ProgressEvent("issue_started", {"issue_number": 10}))
        assert q1.get_nowait().event_type == "issue_started"  # type: ignore[union-attr]
        assert q2.get_nowait().event_type == "issue_started"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self) -> None:
        bus = ProgressBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.publish(ProgressEvent("run_state", {}))
        assert q.empty()

    @pytest.mark.asyncio
    async def test_run_state_replayed_to_new_subscriber(self) -> None:
        bus = ProgressBus()
        bus.publish(ProgressEvent("run_state", {"run_id": 5, "status": "running"}))

        q = bus.subscribe()
        replayed = q.get_nowait()
        assert replayed is not None
        assert replayed.event_type == "run_state"
        assert replayed.data["run_id"] == 5

    @pytest.mark.asyncio
    async def test_non_run_state_events_not_replayed(self) -> None:
        bus = ProgressBus()
        bus.publish(ProgressEvent("issue_started", {"issue_number": 1}))

        q = bus.subscribe()
        assert q.empty()

    @pytest.mark.asyncio
    async def test_close_all_sends_none_sentinel(self) -> None:
        bus = ProgressBus()
        q = bus.subscribe()
        bus.close_all()
        sentinel = q.get_nowait()
        assert sentinel is None

    @pytest.mark.asyncio
    async def test_close_all_clears_run_state(self) -> None:
        bus = ProgressBus()
        bus.publish(ProgressEvent("run_state", {"status": "running"}))
        bus.close_all()

        q = bus.subscribe()
        assert q.empty()

    @pytest.mark.asyncio
    async def test_close_all_reaches_all_subscribers(self) -> None:
        bus = ProgressBus()
        queues = [bus.subscribe() for _ in range(3)]
        bus.close_all()
        for q in queues:
            assert q.get_nowait() is None

    @pytest.mark.asyncio
    async def test_full_queue_does_not_raise(self) -> None:
        bus = ProgressBus()
        bus.subscribe()
        for i in range(600):
            bus.publish(ProgressEvent("session_event", {"i": i}))


class TestSSEEndpoint:
    def _make_app(self, bus: ProgressBus) -> tuple[FastAPI, str]:
        from app.auth.sessions import SessionStore
        from app.main import create_app

        session_store = SessionStore()
        sid = session_store.create()
        return create_app(session_store=session_store, progress_bus=bus), sid

    def test_unauthenticated_request_returns_401(self) -> None:
        from fastapi.testclient import TestClient

        bus = ProgressBus()
        app, _ = self._make_app(bus)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/runs/1/progress")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_stream_emits_events_and_closes(self) -> None:
        """Engine-mocked: publish events via bus and verify SSE output."""
        import httpx

        bus = ProgressBus()
        app, sid = self._make_app(bus)

        events_received: list[dict[str, object]] = []

        async def read_stream() -> None:
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream(
                    "GET",
                    "/runs/1/progress",
                    cookies={"session_id": sid},
                    timeout=5.0,
                ) as resp,
            ):
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
                current_event: str | None = None
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and current_event is not None:
                        payload = json.loads(line.split(":", 1)[1].strip())
                        events_received.append({"type": current_event, "data": payload})
                        if current_event == "run_ended":
                            break
                        current_event = None

        async def feed() -> None:
            await asyncio.sleep(0.05)
            bus.publish(ProgressEvent("run_state", {"run_id": 1, "status": "running"}))
            await asyncio.sleep(0.05)
            bus.publish(ProgressEvent("issue_started", {"run_id": 1, "issue_number": 42}))
            await asyncio.sleep(0.05)
            bus.close_all()

        await asyncio.gather(read_stream(), feed())

        types = [e["type"] for e in events_received]
        assert "run_state" in types
        assert "issue_started" in types
        assert "run_ended" in types

    @pytest.mark.asyncio
    async def test_stream_headers_disable_buffering(self) -> None:
        import httpx

        bus = ProgressBus()
        app, sid = self._make_app(bus)

        async def close_immediately() -> None:
            await asyncio.sleep(0.05)
            bus.close_all()

        headers_seen: dict[str, str] = {}

        async def read_headers() -> None:
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(transport=transport, base_url="http://test") as client,
                client.stream(
                    "GET",
                    "/runs/1/progress",
                    cookies={"session_id": sid},
                    timeout=3.0,
                ) as resp,
            ):
                headers_seen.update(dict(resp.headers))
                async for _ in resp.aiter_lines():
                    break

        await asyncio.gather(read_headers(), close_immediately())

        assert headers_seen.get("cache-control") == "no-cache"
        assert headers_seen.get("x-accel-buffering") == "no"

    @pytest.mark.asyncio
    async def test_reconnect_replays_run_state(self) -> None:
        """A new subscriber always receives the last run_state snapshot."""
        bus = ProgressBus()
        bus.publish(ProgressEvent("run_state", {"run_id": 7, "status": "running"}))

        q = bus.subscribe()
        first = q.get_nowait()
        assert first is not None
        assert first.event_type == "run_state"
        assert first.data["run_id"] == 7
