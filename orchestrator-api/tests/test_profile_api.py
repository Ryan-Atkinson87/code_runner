from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.engine.profile_generation import (
    ProfileGenerationResult,
    ProfileProposal,
    ProposalOutcome,
)
from app.main import create_app
from app.profile.schema import ExecutionProfile, PersonaEntry, PersonaType
from app.providers.types import SessionOutcome, SessionResult
from app.routers import profile as profile_mod
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)

_SAMPLE_YAML = """\
personas:
  - type: implementor
    speciality: backend
stages:
  implement:
    executor: ai
"""


def _make_proposal() -> ProfileProposal:
    return ProfileProposal(
        raw_yaml=_SAMPLE_YAML,
        profile=ExecutionProfile(
            personas=[PersonaEntry(type=PersonaType.IMPLEMENTOR, speciality="backend")]
        ),
        session=SessionResult(outcome=SessionOutcome.COMPLETED),
    )


def _make_success_result() -> ProfileGenerationResult:
    return ProfileGenerationResult(
        outcome=ProposalOutcome.PROPOSED,
        proposal=_make_proposal(),
    )


def _make_error_result() -> ProfileGenerationResult:
    return ProfileGenerationResult(
        outcome=ProposalOutcome.SESSION_ERROR,
        error="Session timed out",
    )


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    generate_fn: Callable[..., Awaitable[ProfileGenerationResult]],
    output_path: Path,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    monkeypatch.setattr(profile_mod, "_pending_proposal", None)
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    app = create_app(
        Settings(),
        session_store=SessionStore(),
        profile_generate_fn=generate_fn,
        profile_output_path=output_path,
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_propose_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml", authed=False)
        assert client.post("/profile/propose").status_code == 401

    def test_confirm_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml", authed=False)
        assert client.post("/profile/confirm").status_code == 401


class TestProposeProfile:
    def test_returns_proposal_yaml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml")
        resp = client.post("/profile/propose")
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "proposed"
        assert "personas" in data["raw_yaml"]

    def test_does_not_write_on_propose(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        out = tmp_path / "out.yaml"
        client = _make_client(monkeypatch, gen, out)
        client.post("/profile/propose")
        assert not out.exists()

    def test_error_returns_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_error_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml")
        resp = client.post("/profile/propose")
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "session_error"
        assert "timed out" in data["error"]


class TestConfirmProfile:
    def test_writes_on_confirm(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        out = tmp_path / "out.yaml"
        client = _make_client(monkeypatch, gen, out)
        client.post("/profile/propose")
        resp = client.post("/profile/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["written"] is True
        assert out.exists()
        assert "personas" in out.read_text()

    def test_confirm_without_proposal_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml")
        resp = client.post("/profile/confirm")
        assert resp.status_code == 409

    def test_double_confirm_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        out = tmp_path / "out.yaml"
        client = _make_client(monkeypatch, gen, out)
        client.post("/profile/propose")
        client.post("/profile/confirm")
        resp = client.post("/profile/confirm")
        assert resp.status_code == 409


class TestRejectProfile:
    def test_reject_clears_proposal(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        out = tmp_path / "out.yaml"
        client = _make_client(monkeypatch, gen, out)
        client.post("/profile/propose")
        resp = client.post("/profile/reject")
        assert resp.status_code == 200
        assert resp.json()["written"] is False
        assert not out.exists()

    def test_confirm_after_reject_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def gen() -> ProfileGenerationResult:
            return _make_success_result()

        client = _make_client(monkeypatch, gen, tmp_path / "out.yaml")
        client.post("/profile/propose")
        client.post("/profile/reject")
        resp = client.post("/profile/confirm")
        assert resp.status_code == 409
