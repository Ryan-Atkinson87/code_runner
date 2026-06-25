from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.github.errors import GitHubError
from app.github.models import PullRequest
from app.main import create_app
from app.routers.prs import _extract_checklist
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)

_PR_BODY = """\
## Summary

Wave P3: 5 completed, 1 parked

## Issues

- Issue: #10 — Add config loader
- Issue: #11 — Add auth module

## Engine-verified checks

- [x] Tests pass
- [x] Lint clean

## Human review checklist

- [ ] Review security implications
- [ ] Check migration safety
- [ ] Verify API contract

## Parked blockers

- **#12:** Spec §5 ambiguous on branch naming
"""

_SAMPLE_PRS = [
    PullRequest(
        number=100,
        title="Wave: P3 – Services",
        body=_PR_BODY,
        html_url="https://github.com/org/repo/pull/100",
        head_branch="code-runner/p3-services",
        base_branch="dev",
        state="open",
    ),
]


def _make_github(
    prs: list[PullRequest] | None = None,
    error: bool = False,
) -> MagicMock:
    client = MagicMock()
    if error:
        client.list_pull_requests.side_effect = GitHubError(
            "API rate limit exceeded", status_code=403
        )
        client.get_pull_request.side_effect = GitHubError(
            "Not found", status_code=404
        )
    else:
        pr_list = prs if prs is not None else _SAMPLE_PRS
        client.list_pull_requests.return_value = pr_list
        if pr_list:
            client.get_pull_request.return_value = pr_list[0]
    return client


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    github: MagicMock,
    authed: bool = True,
) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    if authed:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

    app = create_app(
        Settings(),
        session_store=SessionStore(),
        github_client=github,
        repo_name="test-repo",
    )
    client = TestClient(app, base_url="https://testserver")

    if authed:
        client.post("/login", json={"password": _TEST_PASSWORD})

    return client


class TestAuthGuard:
    def test_list_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch, _make_github(), authed=False)
        assert client.get("/prs").status_code == 401

    def test_get_rejected_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _make_client(monkeypatch, _make_github(), authed=False)
        assert client.get("/prs/100").status_code == 401


class TestListPRs:
    def test_returns_prs_with_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github()
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["prs"]) == 1
        pr = data["prs"][0]
        assert pr["number"] == 100
        assert pr["title"] == "Wave: P3 – Services"
        assert "## Summary" in pr["body"]

    def test_checklist_extracted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github()
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs")
        pr = resp.json()["prs"][0]
        checklist = pr["checklist"]

        engine_checks = [c for c in checklist if c["checked"]]
        human_checks = [c for c in checklist if not c["checked"]]

        assert len(engine_checks) == 2
        assert len(human_checks) == 3
        assert engine_checks[0]["text"] == "Tests pass"
        assert human_checks[0]["text"] == "Review security implications"

    def test_empty_pr_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github(prs=[])
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs")
        assert resp.status_code == 200
        assert resp.json()["prs"] == []

    def test_filters_by_head_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github()
        client = _make_client(monkeypatch, github)

        client.get("/prs?head=code-runner/p3-services")
        github.list_pull_requests.assert_called_with(
            "test-repo", state="open", head="code-runner/p3-services"
        )

    def test_github_error_returns_502(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github(error=True)
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs")
        assert resp.status_code == 502


class TestGetPR:
    def test_returns_single_pr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github()
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs/100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["number"] == 100
        assert data["html_url"] == "https://github.com/org/repo/pull/100"

    def test_github_error_returns_502(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = _make_github(error=True)
        client = _make_client(monkeypatch, github)

        resp = client.get("/prs/999")
        assert resp.status_code == 502


class TestChecklistExtraction:
    def test_extracts_checked_and_unchecked(self) -> None:
        body = "- [x] Done\n- [ ] Not done\n- [X] Also done"
        items = _extract_checklist(body)
        assert len(items) == 3
        assert items[0].checked is True
        assert items[1].checked is False
        assert items[2].checked is True

    def test_empty_body(self) -> None:
        assert _extract_checklist("") == []

    def test_no_checklist(self) -> None:
        assert _extract_checklist("Just some text\nMore text") == []
