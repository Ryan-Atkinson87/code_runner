from __future__ import annotations

import os
from typing import Protocol

import httpx

_DEFAULT_BASE_URL = "http://agent-runner:8000"
_TIMEOUT = httpx.Timeout(310.0)


class ExecutorError(Exception):
    """The agent-runner executor was unreachable, timed out, or rejected the request.

    Raised only for RPC-layer failures — a tool that ran but reported its own error
    (permission denied, bad path, etc.) comes back as a normal 200 response instead.
    """


class ToolExecutor(Protocol):
    """The bash/text-editor RPC surface ``ClaudeAdapter`` depends on."""

    async def bash(self, tool_input: dict[str, object]) -> str: ...

    async def text_editor(self, tool_input: dict[str, object]) -> str: ...


class ExecutorClient:
    """HTTP client for the agent-runner executor's internal bash/text-editor RPC surface.

    Runs tool calls inside agent-runner (Spec §7.1/§7.2) instead of in-process, over the
    private agent_net link added in #257.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
            transport=transport,
        )

    @classmethod
    def from_env(cls) -> ExecutorClient:
        return cls(
            base_url=os.environ.get("AGENT_RUNNER_URL", _DEFAULT_BASE_URL),
            token=os.environ.get("AGENT_RUNNER_TOKEN", ""),
        )

    async def bash(self, tool_input: dict[str, object]) -> str:
        return await self._call("/v1/bash", tool_input)

    async def text_editor(self, tool_input: dict[str, object]) -> str:
        return await self._call("/v1/text-editor", tool_input)

    async def _call(self, path: str, payload: dict[str, object]) -> str:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExecutorError(f"agent-runner executor request to {path} failed: {exc}") from exc
        return str(response.json()["output"])
