from __future__ import annotations

from pathlib import Path

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
