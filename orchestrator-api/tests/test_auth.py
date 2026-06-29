import pytest
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.dependencies import require_auth
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.main import create_app
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)

_protected_router = APIRouter()


@_protected_router.get("/protected")
async def _protected_route(_session: str = Depends(require_auth)) -> dict[str, str]:
    return {"status": "secret"}


def _make_client() -> TestClient:
    store = SessionStore()
    app = create_app(Settings(), session_store=store)
    app.include_router(_protected_router)
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())


class TestLogin:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        response = client.post("/login", json={"password": _TEST_PASSWORD})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "session_id" in response.cookies

    def test_wrong_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        response = client.post("/login", json={"password": "wrong"})
        assert response.status_code == 401
        assert "session_id" not in response.cookies

    def test_missing_hash_env(self) -> None:
        client = _make_client()
        response = client.post("/login", json={"password": "anything"})
        assert response.status_code == 500


class TestProtectedRoute:
    def test_rejected_without_session(self) -> None:
        client = _make_client()
        response = client.get("/protected")
        assert response.status_code == 401

    def test_access_with_valid_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        client.post("/login", json={"password": _TEST_PASSWORD})
        response = client.get("/protected")
        assert response.status_code == 200
        assert response.json()["status"] == "secret"

    def test_rejected_with_invalid_cookie(self) -> None:
        client = _make_client()
        client.cookies.set("session_id", "bogus-token")
        response = client.get("/protected")
        assert response.status_code == 401


class TestLogout:
    def test_invalidates_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        client.post("/login", json={"password": _TEST_PASSWORD})
        client.post("/logout")
        response = client.get("/protected")
        assert response.status_code == 401

    def test_without_session(self) -> None:
        client = _make_client()
        response = client.post("/logout")
        assert response.status_code == 200


class TestSession:
    def test_returns_authenticated_with_valid_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        client.post("/login", json={"password": _TEST_PASSWORD})
        response = client.get("/session")
        assert response.status_code == 200
        assert response.json()["status"] == "authenticated"

    def test_returns_401_without_session(self) -> None:
        client = _make_client()
        response = client.get("/session")
        assert response.status_code == 401


class TestRateLimit:
    def test_blocked_after_max_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter(max_attempts=3))
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        for _ in range(3):
            client.post("/login", json={"password": "wrong"})
        response = client.post("/login", json={"password": _TEST_PASSWORD})
        assert response.status_code == 429

    def test_success_not_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter(max_attempts=3))
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        client = _make_client()
        for _ in range(3):
            resp = client.post("/login", json={"password": _TEST_PASSWORD})
            assert resp.status_code == 200
