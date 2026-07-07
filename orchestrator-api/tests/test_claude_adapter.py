from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.claude import (
    ClaudeAdapter,
    _build_tools,
    _map_stop_reason,
    _normalise_content,
    _tool_result_events,
)
from app.providers.executor_client import ExecutorClient, ExecutorError
from app.providers.types import (
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionResult,
    SessionRole,
    UsageReport,
)
from app.providers.utils import build_prompt, derive_artifacts


def _make_text_block(text: str = "hello") -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _make_thinking_block(thinking: str = "reasoning...") -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking=thinking)


def _make_tool_use_block(
    name: str = "bash",
    input_data: dict[str, Any] | None = None,
    block_id: str = "toolu_123",
) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        name=name,
        input=input_data or {"command": "echo hi"},
        id=block_id,
    )


def _make_usage(input_tokens: int = 100, output_tokens: int = 50) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _make_message(
    content: list[Any] | None = None,
    stop_reason: str = "end_turn",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content or [_make_text_block()],
        stop_reason=stop_reason,
        usage=usage or _make_usage(),
    )


class _FakeExecutor:
    """Stands in for the RPC client, running bash against workdir like agent-runner would.

    Real permission-check and text-editor behaviour are agent-runner's own responsibility
    now (Spec §7.4) and are covered there (agent-runner/tests). This fake only needs to
    reproduce the shared-filesystem effect the real executor has, so adapter-level tests
    that assert on git-derived artifacts stay meaningful.
    """

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    async def bash(self, tool_input: dict[str, Any]) -> str:
        command = str(tool_input.get("command", ""))
        result = subprocess.run(
            ["bash", "-c", command], cwd=self._workdir, capture_output=True, text=True
        )
        return result.stdout or "(no output)"

    async def text_editor(self, tool_input: dict[str, Any]) -> str:
        raise NotImplementedError


class TestBuildTools:
    def test_known_tools(self) -> None:
        tools = _build_tools(["bash", "str_replace_based_edit_tool"])
        assert len(tools) == 2
        assert tools[0]["name"] == "bash"
        assert tools[0]["type"] == "bash_20250124"
        assert tools[1]["name"] == "str_replace_based_edit_tool"
        assert tools[1]["type"] == "text_editor_20250728"

    def test_unknown_tool_skipped(self) -> None:
        tools = _build_tools(["bash", "unknown_tool"])
        assert len(tools) == 1
        assert tools[0]["name"] == "bash"

    def test_empty_list(self) -> None:
        assert _build_tools([]) == []


class TestBuildPrompt:
    def test_prompt_only(self) -> None:
        result = build_prompt("Fix the bug", [])
        assert result == "Fix the bug"

    def test_with_context_files(self, tmp_path: Path) -> None:
        ctx = tmp_path / "issue.md"
        ctx.write_text("Issue #42: broken auth")
        result = build_prompt("Fix it", [ctx])
        assert "Fix it" in result
        assert "Issue #42: broken auth" in result
        assert "issue.md" in result

    def test_missing_context_file_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.md"
        result = build_prompt("Fix it", [missing])
        assert result == "Fix it"


class TestNormaliseContent:
    def test_text_block(self) -> None:
        events = _normalise_content([_make_text_block("output text")])  # type: ignore[arg-type]
        assert len(events) == 1
        assert events[0].kind == EventKind.OUTPUT
        assert events[0].content == "output text"

    def test_thinking_block(self) -> None:
        events = _normalise_content([_make_thinking_block("step 1...")])  # type: ignore[arg-type]
        assert len(events) == 1
        assert events[0].kind == EventKind.REASONING
        assert events[0].content == "step 1..."

    def test_tool_use_block(self) -> None:
        block = _make_tool_use_block("bash", {"command": "ls"})
        events = _normalise_content([block])  # type: ignore[arg-type]
        assert len(events) == 1
        assert events[0].kind == EventKind.TOOL_CALL
        assert events[0].tool_name == "bash"
        assert json.loads(events[0].tool_input or "") == {"command": "ls"}

    def test_mixed_blocks(self) -> None:
        blocks = [
            _make_thinking_block("thinking..."),
            _make_text_block("answer"),
            _make_tool_use_block("bash", {"command": "test"}),
        ]
        events = _normalise_content(blocks)  # type: ignore[arg-type]
        assert len(events) == 3
        assert events[0].kind == EventKind.REASONING
        assert events[1].kind == EventKind.OUTPUT
        assert events[2].kind == EventKind.TOOL_CALL

    def test_timestamps_set(self) -> None:
        events = _normalise_content([_make_text_block()])  # type: ignore[arg-type]
        assert events[0].timestamp > 0


class TestToolResultEvents:
    def test_single_result(self) -> None:
        blocks = [_make_tool_use_block("bash")]
        results: list[dict[str, object]] = [
            {"type": "tool_result", "tool_use_id": "toolu_123", "content": "done"},
        ]
        events = _tool_result_events(blocks, results)  # type: ignore[arg-type]
        assert len(events) == 1
        assert events[0].kind == EventKind.TOOL_RESULT
        assert events[0].tool_name == "bash"
        assert events[0].content == "done"

    def test_multiple_results(self) -> None:
        blocks = [
            _make_tool_use_block("bash", block_id="t1"),
            _make_tool_use_block("str_replace_based_edit_tool", block_id="t2"),
        ]
        results: list[dict[str, object]] = [
            {"type": "tool_result", "tool_use_id": "t1", "content": "output1"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "output2"},
        ]
        events = _tool_result_events(blocks, results)  # type: ignore[arg-type]
        assert len(events) == 2
        assert events[0].tool_name == "bash"
        assert events[1].tool_name == "str_replace_based_edit_tool"


class TestMapStopReason:
    def test_end_turn(self) -> None:
        assert _map_stop_reason("end_turn") == SessionOutcome.COMPLETED

    def test_max_tokens(self) -> None:
        assert _map_stop_reason("max_tokens") == SessionOutcome.COMPLETED

    def test_stop_sequence(self) -> None:
        assert _map_stop_reason("stop_sequence") == SessionOutcome.COMPLETED

    def test_refusal(self) -> None:
        assert _map_stop_reason("refusal") == SessionOutcome.BLOCKED

    def test_none(self) -> None:
        assert _map_stop_reason(None) == SessionOutcome.COMPLETED

    def test_unknown(self) -> None:
        assert _map_stop_reason("something_unexpected") == SessionOutcome.ERROR


class TestDeriveArtifacts:
    def _init_repo(self, tmp_path: Path) -> MagicMock:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "initial.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        repo = MagicMock()
        repo.path = tmp_path
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
        )
        repo.rev_parse.return_value = result.stdout.strip()
        return repo

    @pytest.mark.asyncio
    async def test_uncommitted_changes(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        head_before = repo.rev_parse("HEAD")
        (tmp_path / "new_file.py").write_text("x = 1")
        (tmp_path / "initial.txt").write_text("modified")
        artifacts = await derive_artifacts(repo, head_before)
        assert "new_file.py" in artifacts
        assert "initial.txt" in artifacts

    @pytest.mark.asyncio
    async def test_no_changes(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        head_before = repo.rev_parse("HEAD")
        artifacts = await derive_artifacts(repo, head_before)
        assert artifacts == []

    @pytest.mark.asyncio
    async def test_committed_changes(self, tmp_path: Path) -> None:
        repo = self._init_repo(tmp_path)
        head_before = repo.rev_parse("HEAD")
        (tmp_path / "committed.py").write_text("y = 2")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add file"], cwd=tmp_path, capture_output=True)
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
        )
        repo.rev_parse.return_value = result.stdout.strip()
        artifacts = await derive_artifacts(repo, head_before)
        assert "committed.py" in artifacts


class TestClaudeAdapterRunSession:
    """Integration-level tests with the SDK mocked."""

    def _setup_git_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "existing.py").write_text("old = True")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        return tmp_path

    def _mock_client(self, responses: list[SimpleNamespace]) -> AsyncMock:
        client = AsyncMock()
        stream_mocks = []
        for resp in responses:
            stream_ctx = AsyncMock()
            stream_ctx.__aenter__ = AsyncMock(return_value=stream_ctx)
            stream_ctx.__aexit__ = AsyncMock(return_value=False)
            stream_ctx.get_final_message = AsyncMock(return_value=resp)
            stream_mocks.append(stream_ctx)
        client.messages.stream = MagicMock(side_effect=stream_mocks)
        return client

    @pytest.mark.asyncio
    async def test_simple_text_response(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        message = _make_message(
            content=[_make_text_block("All done!")],
            stop_reason="end_turn",
            usage=_make_usage(200, 80),
        )
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=[],
            prompt="Do nothing",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.COMPLETED
        assert len(result.events) == 1
        assert result.events[0].kind == EventKind.OUTPUT
        assert result.events[0].content == "All done!"
        assert result.usage.tokens_in == 200
        assert result.usage.tokens_out == 80
        assert result.usage.model == "claude-sonnet-4-6"
        assert result.usage.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_thinking_then_text(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        message = _make_message(
            content=[
                _make_thinking_block("Let me think..."),
                _make_text_block("Here is the answer"),
            ],
            stop_reason="end_turn",
        )
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=[],
            prompt="Solve this",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.COMPLETED
        assert len(result.events) == 2
        assert result.events[0].kind == EventKind.REASONING
        assert result.events[1].kind == EventKind.OUTPUT

    @pytest.mark.asyncio
    async def test_tool_use_loop(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)

        tool_call_response = _make_message(
            content=[
                _make_text_block("Let me run a command"),
                _make_tool_use_block("bash", {"command": "echo modified > new.txt"}, "t1"),
            ],
            stop_reason="tool_use",
            usage=_make_usage(150, 60),
        )
        final_response = _make_message(
            content=[_make_text_block("Done!")],
            stop_reason="end_turn",
            usage=_make_usage(250, 40),
        )
        client = self._mock_client([tool_call_response, final_response])
        adapter = ClaudeAdapter(client, executor=_FakeExecutor(workdir))

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Create a file",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.COMPLETED
        assert result.usage.tokens_in == 400
        assert result.usage.tokens_out == 100

        kinds = [e.kind for e in result.events]
        assert EventKind.TOOL_CALL in kinds
        assert EventKind.TOOL_RESULT in kinds
        assert EventKind.OUTPUT in kinds

    @pytest.mark.asyncio
    async def test_refusal_maps_to_blocked(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        message = _make_message(
            content=[_make_text_block("I can't do that")],
            stop_reason="refusal",
        )
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=[],
            prompt="Do something forbidden",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.BLOCKED

    @pytest.mark.asyncio
    async def test_api_error_maps_to_error(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        client = AsyncMock()
        stream_ctx = AsyncMock()
        stream_ctx.__aenter__ = AsyncMock(side_effect=Exception("API Error"))
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        client.messages.stream = MagicMock(return_value=stream_ctx)
        adapter = ClaudeAdapter(client)

        with patch("app.providers.claude.anthropic") as mock_anthropic:
            mock_anthropic.APIError = type("APIError", (Exception,), {})
            mock_anthropic.APIConnectionError = type("APIConnectionError", (Exception,), {})
            stream_ctx.__aenter__ = AsyncMock(side_effect=mock_anthropic.APIError("boom"))
            result = await adapter.run_session(
                workdir=workdir,
                role=SessionRole.IMPLEMENTOR,
                model="claude-sonnet-4-6",
                allowed_tools=[],
                prompt="Trigger error",
                context_files=[],
            )
            assert result.outcome == SessionOutcome.ERROR

    @pytest.mark.asyncio
    async def test_executor_unreachable_maps_to_error(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        tool_call = _make_message(
            content=[_make_tool_use_block("bash", {"command": "echo hi"}, "t1")],
            stop_reason="tool_use",
        )
        client = self._mock_client([tool_call])
        executor = AsyncMock(spec=ExecutorClient)
        executor.bash.side_effect = ExecutorError("agent-runner executor unreachable")
        adapter = ClaudeAdapter(client, executor=executor)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Run a command",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.ERROR

    @pytest.mark.asyncio
    async def test_git_derived_artifacts(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)

        tool_call = _make_message(
            content=[
                _make_tool_use_block(
                    "bash",
                    {"command": "echo 'new content' > created.py"},
                    "t1",
                ),
            ],
            stop_reason="tool_use",
        )
        final = _make_message(
            content=[_make_text_block("Done")],
            stop_reason="end_turn",
        )
        client = self._mock_client([tool_call, final])
        adapter = ClaudeAdapter(client, executor=_FakeExecutor(workdir))

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Create a file",
            context_files=[],
        )

        assert "created.py" in result.artifacts

    @pytest.mark.asyncio
    async def test_context_files_loaded(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("Important context here")

        message = _make_message(stop_reason="end_turn")
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=[],
            prompt="Use the context",
            context_files=[ctx_file],
        )

        call_kwargs = client.messages.stream.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        user_content = messages[0]["content"]
        assert "Important context here" in user_content

    @pytest.mark.asyncio
    async def test_model_passed_to_sdk(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        message = _make_message(stop_reason="end_turn")
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-opus-4-8",
            allowed_tools=[],
            prompt="Test",
            context_files=[],
        )

        call_kwargs = client.messages.stream.call_args
        model = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert model == "claude-opus-4-8"

    @pytest.mark.asyncio
    async def test_no_claude_types_in_result(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        message = _make_message(
            content=[_make_thinking_block(), _make_text_block()],
            stop_reason="end_turn",
        )
        client = self._mock_client([message])
        adapter = ClaudeAdapter(client)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=[],
            prompt="Test",
            context_files=[],
        )

        assert isinstance(result, SessionResult)
        assert isinstance(result.usage, UsageReport)
        for event in result.events:
            assert isinstance(event, NormalisedEvent)
        for artifact in result.artifacts:
            assert isinstance(artifact, str)


class TestClaudeAdapterHooks:
    """Tests that the adapter maps executor RPC responses into audit records/events.

    Permission enforcement itself now runs inside agent-runner (Spec §7.4) and is
    covered there (agent-runner/tests/test_hooks.py, test_routes.py). These tests
    confirm the adapter correctly turns a "Permission denied: ..." response from the
    executor into a blocked audit record and an error tool-result.
    """

    def _setup_git_repo(self, tmp_path: Path) -> Path:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "existing.py").write_text("old = True")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        return tmp_path

    def _mock_client(self, responses: list[SimpleNamespace]) -> AsyncMock:
        client = AsyncMock()
        stream_mocks = []
        for resp in responses:
            stream_ctx = AsyncMock()
            stream_ctx.__aenter__ = AsyncMock(return_value=stream_ctx)
            stream_ctx.__aexit__ = AsyncMock(return_value=False)
            stream_ctx.get_final_message = AsyncMock(return_value=resp)
            stream_mocks.append(stream_ctx)
        client.messages.stream = MagicMock(side_effect=stream_mocks)
        return client

    def _mock_executor(self, bash_output: str) -> AsyncMock:
        executor = AsyncMock(spec=ExecutorClient)
        executor.bash.return_value = bash_output
        return executor

    @pytest.mark.asyncio
    async def test_blocked_tool_returns_permission_denied(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        tool_call = _make_message(
            content=[
                _make_tool_use_block("bash", {"command": "cat .env"}, "t1"),
            ],
            stop_reason="tool_use",
        )
        final = _make_message(
            content=[_make_text_block("OK, I won't do that")],
            stop_reason="end_turn",
        )
        client = self._mock_client([tool_call, final])
        executor = self._mock_executor(
            "Permission denied: bash command references secret files (.env): cat .env"
        )
        adapter = ClaudeAdapter(client, executor=executor)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Read secrets",
            context_files=[],
        )

        assert result.outcome == SessionOutcome.COMPLETED
        tool_results = [e for e in result.events if e.kind == EventKind.TOOL_RESULT]
        assert any("Permission denied" in e.content for e in tool_results)

    @pytest.mark.asyncio
    async def test_blocked_tool_produces_audit_record(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        tool_call = _make_message(
            content=[
                _make_tool_use_block("bash", {"command": "cat .env"}, "t1"),
            ],
            stop_reason="tool_use",
        )
        final = _make_message(
            content=[_make_text_block("OK")],
            stop_reason="end_turn",
        )
        client = self._mock_client([tool_call, final])
        executor = self._mock_executor(
            "Permission denied: bash command references secret files (.env): cat .env"
        )
        adapter = ClaudeAdapter(client, executor=executor)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Read secrets",
            context_files=[],
        )

        assert len(result.audit_log) == 1
        assert result.audit_log[0].blocked is True
        assert "secret" in result.audit_log[0].block_reason

    @pytest.mark.asyncio
    async def test_allowed_tool_produces_audit_record(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        tool_call = _make_message(
            content=[
                _make_tool_use_block("bash", {"command": "echo hello"}, "t1"),
            ],
            stop_reason="tool_use",
        )
        final = _make_message(
            content=[_make_text_block("Done")],
            stop_reason="end_turn",
        )
        client = self._mock_client([tool_call, final])
        executor = self._mock_executor("hello\n")
        adapter = ClaudeAdapter(client, executor=executor)

        result = await adapter.run_session(
            workdir=workdir,
            role=SessionRole.IMPLEMENTOR,
            model="claude-sonnet-4-6",
            allowed_tools=["bash"],
            prompt="Say hello",
            context_files=[],
        )

        assert len(result.audit_log) == 1
        assert result.audit_log[0].blocked is False
        assert result.audit_log[0].tool_name == "bash"


class TestClaudeAdapterIsProviderAdapter:
    def test_isinstance(self) -> None:
        from app.providers.adapter import ProviderAdapter

        client = AsyncMock()
        adapter = ClaudeAdapter(client)
        assert isinstance(adapter, ProviderAdapter)
