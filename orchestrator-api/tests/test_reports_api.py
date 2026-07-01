from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.db.migrations import ALL_MIGRATIONS
from app.main import create_app
from app.observability.models import SessionCapture
from app.observability.rollup import RollupStore
from app.providers.types import SessionOutcome, SessionRole, UsageReport
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "secret"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)


def _init_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    for migration_cls in ALL_MIGRATIONS:
        m = migration_cls()
        m.apply(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
            (m.version, m.description),
        )
    conn.commit()
    return conn


def _capture(
    *,
    session_id: str | None = None,
    wave: str = "P6",
    issue_number: int = 1,
    role: SessionRole = SessionRole.IMPLEMENTOR,
    skill: str = "implement",
    model: str = "claude-sonnet-4-6",
    month_dt: datetime | None = None,
    tokens_in: int = 1000,
    tokens_out: int = 400,
    cost_usd: float = 0.01,
    retry_count: int = 0,
    outcome: SessionOutcome = SessionOutcome.COMPLETED,
) -> SessionCapture:
    dt = month_dt or datetime(2026, 6, 15, tzinfo=UTC)
    return SessionCapture(
        session_id=session_id or uuid.uuid4().hex,
        run_id=1,
        wave=wave,
        issue_number=issue_number,
        role=role,
        skill=skill,
        model=model,
        started_at=dt,
        finished_at=dt,
        usage=UsageReport(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            model=model,
            duration_seconds=60.0,
        ),
        outcome=outcome,
        retry_count=retry_count,
    )


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    store: RollupStore | None = None,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    rollup_store = store or RollupStore(_init_conn())
    app = create_app(
        Settings(),
        session_store=SessionStore(),
        rollup_store=rollup_store,
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_on_demand_rejected_unauthenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch, authed=False)
        assert client.get("/reports").status_code == 401

    def test_wave_rejected_unauthenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch, authed=False)
        assert client.get("/reports/wave/P6").status_code == 401

    def test_month_rejected_unauthenticated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch, authed=False)
        assert client.get("/reports/month/2026-06").status_code == 401


class TestOnDemandReport:
    def test_empty_store_returns_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/reports")
        assert resp.status_code == 200

    def test_scope_is_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        data = client.get("/reports").json()
        assert data["scope"] == "all"

    def test_empty_store_zero_sessions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        data = client.get("/reports").json()
        assert data["total_sessions"] == 0
        assert data["total_cost_usd"] == 0.0

    def test_sessions_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a"))
        store.aggregate_session(_capture(session_id="b"))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports").json()
        assert data["total_sessions"] == 2

    def test_token_breakdown_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", tokens_in=500, tokens_out=200))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports").json()
        tokens = data["tokens"]
        assert tokens["total_in"] == 500
        assert tokens["total_out"] == 200

    def test_generated_at_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        data = client.get("/reports").json()
        assert "generated_at" in data
        assert data["generated_at"] is not None

    def test_model_outcomes_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(
            _capture(session_id="a", model="claude-sonnet-4-6", outcome=SessionOutcome.COMPLETED)
        )
        client = _make_client(monkeypatch, store)
        data = client.get("/reports").json()
        assert len(data["model_outcomes"]) == 1
        mo = data["model_outcomes"][0]
        assert mo["model"] == "claude-sonnet-4-6"
        assert mo["completed_count"] == 1
        assert "completion_rate" in mo

    def test_suggestions_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", tokens_in=5000, tokens_out=100))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports").json()
        assert isinstance(data["suggestions"], list)

    def test_regressions_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        data = client.get("/reports").json()
        assert isinstance(data["regressions"], list)


class TestWaveReport:
    def test_scope_is_wave_prefixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", wave="P6"))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports/wave/P6").json()
        assert data["scope"] == "wave:P6"

    def test_filters_to_requested_wave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", wave="P6"))
        store.aggregate_session(_capture(session_id="b", wave="P7"))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports/wave/P6").json()
        assert data["total_sessions"] == 1

    def test_unknown_wave_returns_empty_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/reports/wave/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total_sessions"] == 0

    def test_token_breakdown_for_wave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", wave="P6", tokens_in=800, tokens_out=300))
        store.aggregate_session(
            _capture(session_id="b", wave="P7", tokens_in=9999, tokens_out=9999)
        )
        client = _make_client(monkeypatch, store)
        data = client.get("/reports/wave/P6").json()
        assert data["tokens"]["total_in"] == 800
        assert data["tokens"]["total_out"] == 300


class TestErrorPath:
    def test_on_demand_returns_500_on_generation_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.routers.reports as reports_mod

        store = RollupStore(_init_conn())
        client = _make_client(monkeypatch, store)

        monkeypatch.setattr(
            reports_mod._generator,
            "generate_on_demand",
            lambda _s: (_ for _ in ()).throw(RuntimeError("db error")),
        )
        resp = client.get("/reports")
        assert resp.status_code == 500
        assert "failed" in resp.json()["detail"].lower()

    def test_wave_returns_500_on_generation_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.routers.reports as reports_mod

        store = RollupStore(_init_conn())
        client = _make_client(monkeypatch, store)

        monkeypatch.setattr(
            reports_mod._generator,
            "generate_for_wave",
            lambda _s, _w: (_ for _ in ()).throw(RuntimeError("db error")),
        )
        resp = client.get("/reports/wave/P6")
        assert resp.status_code == 500

    def test_month_returns_500_on_generation_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.routers.reports as reports_mod

        store = RollupStore(_init_conn())
        client = _make_client(monkeypatch, store)

        monkeypatch.setattr(
            reports_mod._generator,
            "generate_for_month",
            lambda _s, _m: (_ for _ in ()).throw(RuntimeError("db error")),
        )
        resp = client.get("/reports/month/2026-06")
        assert resp.status_code == 500


class TestMonthReport:
    def test_scope_is_month_prefixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", month_dt=datetime(2026, 6, 1, tzinfo=UTC)))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports/month/2026-06").json()
        assert data["scope"] == "month:2026-06"

    def test_filters_to_requested_month(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = RollupStore(_init_conn())
        store.aggregate_session(_capture(session_id="a", month_dt=datetime(2026, 6, 1, tzinfo=UTC)))
        store.aggregate_session(_capture(session_id="b", month_dt=datetime(2026, 7, 1, tzinfo=UTC)))
        client = _make_client(monkeypatch, store)
        data = client.get("/reports/month/2026-06").json()
        assert data["total_sessions"] == 1

    def test_unknown_month_returns_empty_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/reports/month/2099-01")
        assert resp.status_code == 200
        assert resp.json()["total_sessions"] == 0
