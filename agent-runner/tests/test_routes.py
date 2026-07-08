from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(token="test-token", workdir=str(tmp_path))
    return TestClient(create_app(settings))


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _async_client(tmp_path: Path) -> httpx.AsyncClient:
    settings = Settings(token="test-token", workdir=str(tmp_path))
    transport = httpx.ASGITransport(app=create_app(settings))
    return httpx.AsyncClient(transport=transport, base_url="http://agent-runner")


class TestHealth:
    def test_health_no_auth_required(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "agent-runner"}


class TestAuth:
    def test_missing_token_rejected(self, client: TestClient) -> None:
        response = client.post("/v1/bash", json={"command": "echo hi"})
        assert response.status_code == 401

    def test_wrong_token_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/bash",
            json={"command": "echo hi"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert response.status_code == 401

    def test_unconfigured_token_rejects_everything(self, tmp_path: Path) -> None:
        settings = Settings(token="", workdir=str(tmp_path))
        unauth_client = TestClient(create_app(settings))
        response = unauth_client.post(
            "/v1/bash",
            json={"command": "echo hi"},
            headers={"Authorization": "Bearer anything"},
        )
        assert response.status_code == 503


class TestBashEndpoint:
    def test_successful_command(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.post("/v1/bash", json={"command": "echo hello"}, headers=auth_headers)
        assert response.status_code == 200
        assert "hello" in response.json()["output"]

    def test_permission_denied_surfaces_as_output(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/bash", json={"command": "cat .env"}, headers=auth_headers)
        assert response.status_code == 200
        assert "Permission denied" in response.json()["output"]

    def test_restart(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.post("/v1/bash", json={"restart": True}, headers=auth_headers)
        assert response.status_code == 200
        assert "restarted" in response.json()["output"].lower()


class TestTextEditorEndpoint:
    def test_create_and_view(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        create_response = client.post(
            "/v1/text-editor",
            json={"command": "create", "path": "new.py", "file_text": "x = 1"},
            headers=auth_headers,
        )
        assert create_response.status_code == 200
        assert "Created" in create_response.json()["output"]
        assert (tmp_path / "new.py").read_text() == "x = 1"

        view_response = client.post(
            "/v1/text-editor",
            json={"command": "view", "path": "new.py"},
            headers=auth_headers,
        )
        assert "x = 1" in view_response.json()["output"]

    def test_permission_denied_surfaces_as_output(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/text-editor",
            json={"command": "view", "path": ".env"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "Permission denied" in response.json()["output"]

    def test_path_traversal_surfaces_as_output(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/text-editor",
            json={"command": "view", "path": "../../etc/passwd"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "outside" in response.json()["output"].lower()


class TestConcurrency:
    """Two in-flight AI sessions can hit the executor at once (Spec §4.2 concurrency cap).

    These exercise real concurrent HTTP requests (ASGITransport + asyncio.gather), not
    sequential TestClient calls, so a regression that serialises requests or leaks state
    between them would actually show up here.
    """

    @pytest.mark.asyncio
    async def test_concurrent_bash_calls_run_in_parallel_without_interference(
        self, tmp_path: Path, auth_headers: dict[str, str]
    ) -> None:
        async with _async_client(tmp_path) as client:
            start = time.monotonic()
            responses = await asyncio.gather(
                client.post(
                    "/v1/bash",
                    json={"command": "sleep 0.3 && echo first"},
                    headers=auth_headers,
                ),
                client.post(
                    "/v1/bash",
                    json={"command": "sleep 0.3 && echo second"},
                    headers=auth_headers,
                ),
            )
        elapsed = time.monotonic() - start

        assert "first" in responses[0].json()["output"]
        assert "second" in responses[1].json()["output"]
        # If the two sleeps ran sequentially this would take ~0.6s; a generous ceiling
        # below that proves they actually overlapped instead of queueing.
        assert elapsed < 0.55

    @pytest.mark.asyncio
    async def test_concurrent_text_editor_calls_do_not_cross_contaminate(
        self, tmp_path: Path, auth_headers: dict[str, str]
    ) -> None:
        async with _async_client(tmp_path) as client:
            responses = await asyncio.gather(
                client.post(
                    "/v1/text-editor",
                    json={"command": "create", "path": "a.py", "file_text": "a_content"},
                    headers=auth_headers,
                ),
                client.post(
                    "/v1/text-editor",
                    json={"command": "create", "path": "b.py", "file_text": "b_content"},
                    headers=auth_headers,
                ),
            )

        assert all(r.status_code == 200 for r in responses)
        assert (tmp_path / "a.py").read_text() == "a_content"
        assert (tmp_path / "b.py").read_text() == "b_content"

    @pytest.mark.asyncio
    async def test_concurrent_requests_each_get_their_own_response(
        self, tmp_path: Path, auth_headers: dict[str, str]
    ) -> None:
        async with _async_client(tmp_path) as client:
            commands = [f"echo request-{i}" for i in range(8)]
            responses = await asyncio.gather(
                *(
                    client.post("/v1/bash", json={"command": cmd}, headers=auth_headers)
                    for cmd in commands
                )
            )

        for i, response in enumerate(responses):
            assert f"request-{i}" in response.json()["output"]
