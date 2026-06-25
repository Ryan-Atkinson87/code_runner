from __future__ import annotations

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.config.schema import (
    GitHubIntegration,
    IntegrationsSection,
    ProjectConfig,
    ProjectSection,
    RepoEntry,
)
from app.main import create_app
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)


def _make_config() -> ProjectConfig:
    return ProjectConfig(
        project=ProjectSection(name="test-project", description="A test"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-org")
        ),
        repos=[RepoEntry(name="api", path="./api")],
        secrets={"GITHUB_PAT": "GITHUB_PAT", "API_KEY": "API_KEY"},
    )


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    config: ProjectConfig | None = None,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    app = create_app(
        Settings(),
        session_store=SessionStore(),
        project_config=config or _make_config(),
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_read_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch, authed=False)
        assert client.get("/config").status_code == 401

    def test_update_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch, authed=False)
        resp = client.put(
            "/config/provider", json={"default": "codex"}
        )
        assert resp.status_code == 401


class TestReadConfig:
    def test_returns_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_name"] == "test-project"
        assert data["project_description"] == "A test"

    def test_secrets_are_references_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/config")
        secrets = resp.json()["secrets"]
        assert secrets["GITHUB_PAT"] == "GITHUB_PAT"
        assert secrets["API_KEY"] == "API_KEY"

    def test_provider_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/config")
        provider = resp.json()["provider"]
        assert provider["default"] == "claude"

    def test_notifications_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.get("/config")
        notif = resp.json()["notifications"]
        assert notif["telegram"] is True
        assert notif["email"] is False


class TestUpdateProvider:
    def test_update_default_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/provider", json={"default": "codex"}
        )
        assert resp.status_code == 200
        assert resp.json()["provider"]["default"] == "codex"

    def test_update_plan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/provider", json={"plan": "max"}
        )
        assert resp.status_code == 200
        assert resp.json()["provider"]["plan"] == "max"

    def test_invalid_provider_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/provider", json={"default": "openai"}
        )
        assert resp.status_code == 422


class TestUpdateEgress:
    def test_update_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/egress",
            json={"allow": ["api.github.com", "pypi.org"]},
        )
        assert resp.status_code == 200
        assert resp.json()["egress"]["allow"] == [
            "api.github.com", "pypi.org"
        ]

    def test_empty_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put("/config/egress", json={"allow": []})
        assert resp.status_code == 200
        assert resp.json()["egress"]["allow"] == []


class TestNotificationToggle:
    def test_toggle_email_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/notifications", json={"email": True}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notifications"]["email"] is True
        assert data["notifications"]["telegram"] is True

    def test_toggle_telegram_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/notifications", json={"telegram": False}
        )
        assert resp.status_code == 200
        assert resp.json()["notifications"]["telegram"] is False

    def test_toggle_both(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        resp = client.put(
            "/config/notifications",
            json={"telegram": False, "email": True},
        )
        assert resp.status_code == 200
        notif = resp.json()["notifications"]
        assert notif["telegram"] is False
        assert notif["email"] is True

    def test_toggle_persists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch)
        client.put("/config/notifications", json={"email": True})
        resp = client.get("/config")
        assert resp.json()["notifications"]["email"] is True
