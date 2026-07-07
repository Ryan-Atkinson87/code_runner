from __future__ import annotations

import httpx
import pytest

from app.providers.executor_client import ExecutorClient, ExecutorError


def _client_with_transport(transport: httpx.MockTransport) -> ExecutorClient:
    return ExecutorClient(base_url="http://agent-runner:8000", token="secret", transport=transport)


class TestExecutorClientFromEnv:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_RUNNER_URL", raising=False)
        monkeypatch.delenv("AGENT_RUNNER_TOKEN", raising=False)
        client = ExecutorClient.from_env()
        assert str(client._client.base_url) == "http://agent-runner:8000"

    def test_reads_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_RUNNER_URL", "http://custom-host:9000")
        monkeypatch.setenv("AGENT_RUNNER_TOKEN", "tok123")
        client = ExecutorClient.from_env()
        assert str(client._client.base_url) == "http://custom-host:9000"
        assert client._client.headers["authorization"] == "Bearer tok123"


class TestExecutorClientBash:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/bash"
            assert request.headers["authorization"] == "Bearer secret"
            return httpx.Response(200, json={"output": "hello\n"})

        client = _client_with_transport(httpx.MockTransport(handler))
        output = await client.bash({"command": "echo hello"})
        assert output == "hello\n"

    @pytest.mark.asyncio
    async def test_permission_denied_is_a_normal_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"output": "Permission denied: secret file"})

        client = _client_with_transport(httpx.MockTransport(handler))
        output = await client.bash({"command": "cat .env"})
        assert output == "Permission denied: secret file"

    @pytest.mark.asyncio
    async def test_unauthorized_raises_executor_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "invalid or missing bearer token"})

        client = _client_with_transport(httpx.MockTransport(handler))
        with pytest.raises(ExecutorError):
            await client.bash({"command": "echo hi"})

    @pytest.mark.asyncio
    async def test_connection_failure_raises_executor_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _client_with_transport(httpx.MockTransport(handler))
        with pytest.raises(ExecutorError):
            await client.bash({"command": "echo hi"})

    @pytest.mark.asyncio
    async def test_timeout_raises_executor_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _client_with_transport(httpx.MockTransport(handler))
        with pytest.raises(ExecutorError):
            await client.bash({"command": "sleep 999"})


class TestExecutorClientTextEditor:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/text-editor"
            return httpx.Response(200, json={"output": "Created foo.py"})

        client = _client_with_transport(httpx.MockTransport(handler))
        output = await client.text_editor(
            {"command": "create", "path": "foo.py", "file_text": "x = 1"}
        )
        assert output == "Created foo.py"
