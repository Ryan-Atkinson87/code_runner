from __future__ import annotations

import sqlite3

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.blockers.models import Blocker, BlockerType
from app.blockers.store import BlockerStore
from app.main import create_app
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)

_RUN_ID = 1


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    from app.db.migrations import ALL_MIGRATIONS

    for migration_cls in ALL_MIGRATIONS:
        migration = migration_cls()
        migration.apply(conn)
    conn.commit()
    conn.execute(
        "INSERT INTO runs (id, project, milestone, status) VALUES (?, ?, ?, ?)",
        (_RUN_ID, "test", "wave-1", "running"),
    )
    conn.commit()
    return conn


@pytest.fixture()
def blocker_store(db_conn: sqlite3.Connection) -> BlockerStore:
    return BlockerStore(db_conn)


def _seed_blockers(store: BlockerStore) -> list[Blocker]:
    b1 = store.record(
        Blocker(
            run_id=_RUN_ID,
            issue_number=10,
            blocker_type=BlockerType.MISSING_SPEC,
            reason="Spec §5 is ambiguous about branch naming",
            needed_to_unblock="Clarify branch naming convention",
        )
    )
    b2 = store.record(
        Blocker(
            run_id=_RUN_ID,
            issue_number=11,
            blocker_type=BlockerType.CONTRACT_CONFLICT,
            reason="API shape conflicts with docs/api.md",
            needed_to_unblock="Resolve contract conflict",
        )
    )
    return [b1, b2]


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    blocker_store: BlockerStore,
    run_id: int | None = _RUN_ID,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    app = create_app(
        Settings(),
        session_store=SessionStore(),
        blocker_store=blocker_store,
        active_run_id_fn=lambda: run_id,
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_list_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store, authed=False)
        assert client.get("/blockers").status_code == 401

    def test_resolve_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store, authed=False)
        resp = client.post(
            "/blockers/10/resolve", json={"response": "fixed"}
        )
        assert resp.status_code == 401


class TestListBlockers:
    def test_returns_parked_blockers(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        _seed_blockers(blocker_store)
        client = _make_client(monkeypatch, blocker_store)

        resp = client.get("/blockers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == _RUN_ID
        assert len(data["blockers"]) == 2

    def test_blocker_fields_present(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        _seed_blockers(blocker_store)
        client = _make_client(monkeypatch, blocker_store)

        resp = client.get("/blockers")
        blocker = resp.json()["blockers"][0]
        assert "issue_number" in blocker
        assert "blocker_type" in blocker
        assert "reason" in blocker
        assert "needed_to_unblock" in blocker
        assert "status" in blocker
        assert blocker["status"] == "parked"

    def test_empty_when_no_blockers(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store)
        resp = client.get("/blockers")
        assert resp.status_code == 200
        assert resp.json()["blockers"] == []

    def test_no_active_run(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store, run_id=None)
        resp = client.get("/blockers")
        assert resp.status_code == 404

    def test_resolved_blockers_excluded(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        _seed_blockers(blocker_store)
        blocker_store.resolve(_RUN_ID, 10, resolution_response="fixed")
        client = _make_client(monkeypatch, blocker_store)

        resp = client.get("/blockers")
        assert len(resp.json()["blockers"]) == 1


class TestResolveBlocker:
    def test_resolves_parked_blocker(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        _seed_blockers(blocker_store)
        client = _make_client(monkeypatch, blocker_store)

        resp = client.post(
            "/blockers/10/resolve",
            json={"response": "Use kebab-case branch names"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolution_response"] == "Use kebab-case branch names"

    def test_uses_same_store_as_telegram(
        self,
        monkeypatch: pytest.MonkeyPatch,
        blocker_store: BlockerStore,
    ) -> None:
        _seed_blockers(blocker_store)
        client = _make_client(monkeypatch, blocker_store)

        client.post(
            "/blockers/10/resolve", json={"response": "resolved via API"}
        )

        parked = blocker_store.list_parked(_RUN_ID)
        assert len(parked) == 1
        assert parked[0].issue_number == 11

    def test_resolve_nonexistent_blocker(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store)
        resp = client.post(
            "/blockers/999/resolve", json={"response": "test"}
        )
        assert resp.status_code == 404

    def test_resolve_requires_response_text(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        _seed_blockers(blocker_store)
        client = _make_client(monkeypatch, blocker_store)
        resp = client.post("/blockers/10/resolve", json={"response": ""})
        assert resp.status_code == 422

    def test_no_active_run(
        self, monkeypatch: pytest.MonkeyPatch, blocker_store: BlockerStore
    ) -> None:
        client = _make_client(monkeypatch, blocker_store, run_id=None)
        resp = client.post(
            "/blockers/10/resolve", json={"response": "test"}
        )
        assert resp.status_code == 404
