from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.engine.scheduler import WaveScheduler
from app.main import create_app
from app.settings import Settings
from app.usage.models import Meter, MeterKind, UsageSnapshot
from app.usage.monitor import MonitorState, UsageMonitor
from app.usage.policy import PolicyAction, UsagePolicy, UsagePolicyState
from app.usage.threshold import ThresholdResult

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)


def _make_snapshot(
    meters: list[Meter] | None = None,
) -> UsageSnapshot:
    return UsageSnapshot(
        meters=meters
        or [
            Meter(kind=MeterKind.FIVE_HOUR, utilisation=45.0, resets_at=1750100000.0),
            Meter(kind=MeterKind.SEVEN_DAY, utilisation=72.0, limit=100.0, used=72.0),
        ],
        timestamp=1750000000.0,
        provider="claude",
        plan="pro",
    )


def _make_monitor_state(
    snapshot: UsageSnapshot | None = None,
    threshold_reached: bool = False,
    override_active: bool = False,
) -> MonitorState:
    snap = snapshot or _make_snapshot()
    governing = max(snap.meters, key=lambda m: m.utilisation) if snap.meters else None
    return MonitorState(
        snapshot=snap,
        threshold=ThresholdResult(
            reached=threshold_reached,
            governing=governing,
            threshold_percent=80,
        ),
        cap_step=None,
        policy_action=PolicyAction.PROCEED,
        policy_state=UsagePolicyState(
            override_active=override_active,
            peak_throttle_active=False,
            in_peak_window=False,
        ),
        governing=governing,
        applicable_meter_kinds=frozenset({MeterKind.FIVE_HOUR, MeterKind.SEVEN_DAY}),
    )


def _make_monitor(state: MonitorState | None = None) -> UsageMonitor:
    reader = AsyncMock()
    policy = UsagePolicy(peak_hour_throttle_enabled=False)
    scheduler = WaveScheduler()
    monitor = UsageMonitor(
        reader=reader,
        policy=policy,
        scheduler=scheduler,
    )
    if state is not None:
        monitor._last_state = state
    return monitor


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    monitor: UsageMonitor,
    policy: UsagePolicy | None = None,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    app = create_app(
        Settings(),
        session_store=SessionStore(),
        usage_monitor=monitor,
        usage_policy=policy or monitor.policy,
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_gauges_rejected_unauthenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor()
        client = _make_client(monkeypatch, monitor, authed=False)
        assert client.get("/usage/gauges").status_code == 401

    def test_override_rejected_unauthenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor()
        client = _make_client(monkeypatch, monitor, authed=False)
        resp = client.post("/usage/override", json={"active": True})
        assert resp.status_code == 401


class TestGetGauges:
    def test_returns_meters_with_governing_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state()
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["meters"]) == 2

        governing_meters = [m for m in data["meters"] if m["is_governing"]]
        assert len(governing_meters) == 1
        assert governing_meters[0]["kind"] == MeterKind.SEVEN_DAY

    def test_includes_threshold_percent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state()
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        data = resp.json()
        assert data["threshold_percent"] == 80

    def test_threshold_reached_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state(threshold_reached=True)
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        assert resp.json()["threshold_reached"] is True

    def test_override_reflected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state(override_active=True)
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        assert resp.json()["override_active"] is True

    def test_empty_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor(state=None)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        assert resp.status_code == 200
        data = resp.json()
        assert data["meters"] == []
        assert data["override_active"] is False

    def test_meter_fields_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state()
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        meter = resp.json()["meters"][0]
        assert "kind" in meter
        assert "utilisation" in meter
        assert "resets_at" in meter
        assert "is_governing" in meter


class TestOverrideToggle:
    def test_activate_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor()
        policy = monitor.policy
        client = _make_client(monkeypatch, monitor, policy)

        assert policy.override_active is False

        resp = client.post("/usage/override", json={"active": True})
        assert resp.status_code == 200
        assert resp.json()["override_active"] is True
        assert policy.override_active is True

    def test_deactivate_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor()
        policy = monitor.policy
        policy.set_override(True)
        client = _make_client(monkeypatch, monitor, policy)

        resp = client.post("/usage/override", json={"active": False})
        assert resp.status_code == 200
        assert resp.json()["override_active"] is False
        assert policy.override_active is False

    def test_dispatches_to_policy_lever(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monitor = _make_monitor()
        policy = monitor.policy
        client = _make_client(monkeypatch, monitor, policy)

        client.post("/usage/override", json={"active": True})
        assert policy.override_active is True

        client.post("/usage/override", json={"active": False})
        assert policy.override_active is False

    def test_provider_and_plan_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _make_monitor_state()
        monitor = _make_monitor(state)
        client = _make_client(monkeypatch, monitor)

        resp = client.get("/usage/gauges")
        data = resp.json()
        assert data["provider"] == "claude"
        assert data["plan"] == "pro"
