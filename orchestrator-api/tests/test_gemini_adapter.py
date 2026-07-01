"""Unit tests for the Gemini CLI adapter using recorded JSONL fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.providers.gemini import (
    GeminiAdapter,
    _build_lockdown_cmd,
    _check_prohibited_ops,
    _is_blocked,
    _map_status,
    _parse_output,
    _validate_lockdown,
)
from app.providers.types import EventKind, NormalisedEvent, SessionOutcome, SessionRole
from app.providers.utils import LockdownError


def _jsonl(*objects: dict) -> str:  # type: ignore[type-arg]
    return "\n".join(json.dumps(o) for o in objects)


FIXTURE_SIMPLE_SESSION = _jsonl(
    {"type": "thought", "text": "I need to check the failing test."},
    {"type": "content", "role": "model", "text": "I'll fix the failing test now."},
    {"type": "tool_call", "name": "run_code", "input": {"language": "python", "code": "import os"}},
    {"type": "tool_result", "name": "run_code", "output": ""},
    {"type": "tool_call", "name": "run_code", "input": {"language": "bash", "code": "pytest"}},
    {"type": "tool_result", "name": "run_code", "output": "1 passed"},
    {"type": "content", "role": "model", "text": "All tests are passing now."},
    {"type": "usage", "prompt_tokens": 400, "candidates_tokens": 130},
    {"type": "done", "status": "completed"},
)

FIXTURE_BLOCKED_SESSION = _jsonl(
    {"type": "content", "role": "model", "text": "I need human input to proceed."},
    {"type": "usage", "prompt_tokens": 80, "candidates_tokens": 15},
    {"type": "done", "status": "cancelled"},
)

FIXTURE_ERROR_SESSION = _jsonl(
    {"type": "content", "role": "model", "text": "Attempting to fix the issue."},
    {"type": "tool_call", "name": "run_code", "input": {"language": "python", "code": "bad()"}},
    {"type": "tool_result", "name": "run_code", "output": "NameError: bad"},
    {"type": "usage", "prompt_tokens": 150, "candidates_tokens": 40},
    {"type": "done", "status": "error"},
)

FIXTURE_MIXED_EVENTS = _jsonl(
    {"type": "unknown_future_type", "data": "ignored"},
    {"type": "content", "role": "user", "text": "ignored — not model"},
    {"type": "thought", "text": "thinking..."},
    {"type": "content", "role": "model", "text": "done"},
    {"type": "usage", "prompt_tokens": 60, "candidates_tokens": 8},
    {"type": "done", "status": "completed"},
)

FIXTURE_USAGE_ONLY = _jsonl(
    {"type": "usage", "prompt_tokens": 1200, "candidates_tokens": 600},
    {"type": "done", "status": "completed"},
)


class TestParseOutput:
    def test_simple_session_event_count(self) -> None:
        events, _, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        assert len(events) == 7

    def test_simple_session_event_kinds(self) -> None:
        events, _, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        kinds = [e.kind for e in events]
        assert kinds[0] == EventKind.REASONING
        assert kinds[1] == EventKind.OUTPUT
        assert kinds[2] == EventKind.TOOL_CALL
        assert kinds[3] == EventKind.TOOL_RESULT
        assert kinds[4] == EventKind.TOOL_CALL
        assert kinds[5] == EventKind.TOOL_RESULT
        assert kinds[6] == EventKind.OUTPUT

    def test_simple_session_usage(self) -> None:
        _, usage, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        assert usage["prompt_tokens"] == 400
        assert usage["candidates_tokens"] == 130

    def test_simple_session_outcome(self) -> None:
        _, _, outcome = _parse_output(FIXTURE_SIMPLE_SESSION)
        assert outcome == SessionOutcome.COMPLETED

    def test_tool_call_event_has_name_and_serialised_input(self) -> None:
        events, _, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        tool_call = events[2]
        assert tool_call.kind == EventKind.TOOL_CALL
        assert tool_call.tool_name == "run_code"
        assert "python" in (tool_call.tool_input or "")

    def test_tool_result_event_has_output(self) -> None:
        events, _, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        tool_result = events[5]
        assert tool_result.kind == EventKind.TOOL_RESULT
        assert "passed" in tool_result.content

    def test_thought_event_maps_to_reasoning(self) -> None:
        events, _, _ = _parse_output(FIXTURE_SIMPLE_SESSION)
        reasoning = events[0]
        assert reasoning.kind == EventKind.REASONING
        assert "failing test" in reasoning.content

    def test_blocked_via_done_status(self) -> None:
        _, _, outcome = _parse_output(FIXTURE_BLOCKED_SESSION)
        assert outcome == SessionOutcome.BLOCKED

    def test_blocked_phrase_in_content_sets_blocked(self) -> None:
        _, _, outcome = _parse_output(FIXTURE_BLOCKED_SESSION)
        assert outcome == SessionOutcome.BLOCKED

    def test_error_via_done_status(self) -> None:
        _, _, outcome = _parse_output(FIXTURE_ERROR_SESSION)
        assert outcome == SessionOutcome.ERROR

    def test_unknown_event_types_ignored(self) -> None:
        events, _, outcome = _parse_output(FIXTURE_MIXED_EVENTS)
        kinds = [e.kind for e in events]
        assert EventKind.REASONING in kinds
        assert EventKind.OUTPUT in kinds
        assert outcome == SessionOutcome.COMPLETED

    def test_non_model_content_ignored(self) -> None:
        events, _, _ = _parse_output(FIXTURE_MIXED_EVENTS)
        output_events = [e for e in events if e.kind == EventKind.OUTPUT]
        assert len(output_events) == 1
        assert output_events[0].content == "done"

    def test_usage_extracted_with_gemini_key_names(self) -> None:
        _, usage, _ = _parse_output(FIXTURE_USAGE_ONLY)
        assert usage["prompt_tokens"] == 1200
        assert usage["candidates_tokens"] == 600

    def test_empty_output_defaults_to_completed(self) -> None:
        _, _, outcome = _parse_output("")
        assert outcome == SessionOutcome.COMPLETED

    def test_empty_output_no_events(self) -> None:
        events, _, _ = _parse_output("")
        assert events == []

    def test_malformed_json_lines_skipped(self) -> None:
        output = 'not-json\n{"type":"done","status":"completed"}\nalso-bad'
        events, _, outcome = _parse_output(output)
        assert outcome == SessionOutcome.COMPLETED
        assert events == []

    def test_blank_lines_skipped(self) -> None:
        output = '\n\n{"type":"done","status":"completed"}\n\n'
        _, _, outcome = _parse_output(output)
        assert outcome == SessionOutcome.COMPLETED


class TestMapStatus:
    def test_completed_maps_to_completed(self) -> None:
        assert _map_status("completed") == SessionOutcome.COMPLETED

    def test_cancelled_maps_to_blocked(self) -> None:
        assert _map_status("cancelled") == SessionOutcome.BLOCKED

    def test_error_maps_to_error(self) -> None:
        assert _map_status("error") == SessionOutcome.ERROR

    def test_unknown_status_maps_to_error(self) -> None:
        assert _map_status("unexpected") == SessionOutcome.ERROR


class TestIsBlocked:
    def test_blocked_phrase_detected(self) -> None:
        assert _is_blocked("I need human input to resolve this.")

    def test_case_insensitive(self) -> None:
        assert _is_blocked("I NEED HUMAN INPUT")

    def test_please_clarify(self) -> None:
        assert _is_blocked("Please clarify what you mean.")

    def test_normal_output_not_blocked(self) -> None:
        assert not _is_blocked("All tests are passing.")

    def test_empty_string_not_blocked(self) -> None:
        assert not _is_blocked("")

    def test_cannot_proceed_without(self) -> None:
        assert _is_blocked("I cannot proceed without more context.")


class TestBuildLockdownCmd:
    def test_includes_sandbox_flag(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "do the thing", SessionRole.IMPLEMENTOR)
        assert "--sandbox" in cmd

    def test_implementor_has_no_readonly(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "do the thing", SessionRole.IMPLEMENTOR)
        assert "--readonly" not in cmd

    def test_orchestrator_has_readonly(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "plan this", SessionRole.ORCHESTRATOR)
        assert "--readonly" in cmd

    def test_includes_model(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "prompt", SessionRole.IMPLEMENTOR)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "gemini-2.5-pro"

    def test_prompt_is_after_p_flag(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "my prompt", SessionRole.IMPLEMENTOR)
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "my prompt"


class TestValidateLockdown:
    def test_valid_cmd_passes(self) -> None:
        cmd = _build_lockdown_cmd("gemini-2.5-pro", "prompt", SessionRole.IMPLEMENTOR)
        _validate_lockdown(cmd)  # must not raise

    def test_missing_sandbox_raises_lockdown_error(self) -> None:
        cmd = ["gemini", "-p", "prompt", "--output-format", "json"]
        with pytest.raises(LockdownError, match="--sandbox"):
            _validate_lockdown(cmd)


class TestCheckProhibitedOps:
    def _tool_event(self, tool_input: str) -> NormalisedEvent:
        return NormalisedEvent(
            kind=EventKind.TOOL_CALL,
            tool_name="run_code",
            tool_input=tool_input,
            timestamp=0.0,
        )

    def test_force_push_long_form_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"git push --force origin feature"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_force_push_short_form_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"git push -f origin feature"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_push_to_main_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"git push origin main"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_push_to_dev_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"git push origin dev"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_env_file_access_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"cat .env"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_env_example_not_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"cat .env.example"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.COMPLETED

    def test_ci_workflow_edit_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"vim .github/workflows/ci.yml"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.BLOCKED

    def test_safe_push_to_feature_not_blocked(self) -> None:
        events = [self._tool_event('{"language":"bash","code":"git push origin feature/new"}')]
        assert _check_prohibited_ops(events) == SessionOutcome.COMPLETED

    def test_non_tool_events_ignored(self) -> None:
        output_event = NormalisedEvent(
            kind=EventKind.OUTPUT,
            content="git push --force origin main",
            timestamp=0.0,
        )
        assert _check_prohibited_ops([output_event]) == SessionOutcome.COMPLETED

    def test_empty_events_not_blocked(self) -> None:
        assert _check_prohibited_ops([]) == SessionOutcome.COMPLETED


class TestGeminiLockdownIntegration:
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
        (tmp_path / "existing.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        return tmp_path

    @pytest.mark.asyncio
    async def test_sandbox_flag_present_on_every_invocation(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmd.extend(cmd)
            result = MagicMock()
            result.stdout = '{"type":"done","status":"completed"}\n'
            result.returncode = 0
            return result

        adapter = GeminiAdapter()
        with patch("app.providers.gemini.subprocess.run", side_effect=fake_run):
            await adapter.run_session(
                workdir=workdir,
                role=SessionRole.IMPLEMENTOR,
                model="gemini-2.5-pro",
                allowed_tools=[],
                prompt="do something",
                context_files=[],
            )

        assert "--sandbox" in captured_cmd

    @pytest.mark.asyncio
    async def test_orchestrator_readonly_flag_present(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        captured_cmd: list[str] = []

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmd.extend(cmd)
            result = MagicMock()
            result.stdout = '{"type":"done","status":"completed"}\n'
            result.returncode = 0
            return result

        adapter = GeminiAdapter()
        with patch("app.providers.gemini.subprocess.run", side_effect=fake_run):
            await adapter.run_session(
                workdir=workdir,
                role=SessionRole.ORCHESTRATOR,
                model="gemini-2.5-pro",
                allowed_tools=[],
                prompt="plan this",
                context_files=[],
            )

        assert "--readonly" in captured_cmd

    @pytest.mark.asyncio
    async def test_prohibited_op_in_output_returns_blocked(self, tmp_path: Path) -> None:
        workdir = self._setup_git_repo(tmp_path)
        output = (
            '{"type":"tool_call","name":"run_code",'
            '"input":{"language":"bash","code":"git push --force origin main"}}\n'
            '{"type":"done","status":"completed"}\n'
        )

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = output
            result.returncode = 0
            return result

        adapter = GeminiAdapter()
        with patch("app.providers.gemini.subprocess.run", side_effect=fake_run):
            result = await adapter.run_session(
                workdir=workdir,
                role=SessionRole.IMPLEMENTOR,
                model="gemini-2.5-pro",
                allowed_tools=[],
                prompt="force push",
                context_files=[],
            )

        assert result.outcome == SessionOutcome.BLOCKED


class TestGeminiAdapterInterface:
    def test_implements_provider_adapter(self) -> None:
        from app.providers.adapter import ProviderAdapter

        assert issubclass(GeminiAdapter, ProviderAdapter)

    def test_instantiates_without_args(self) -> None:
        adapter = GeminiAdapter()
        assert adapter is not None


class TestNoProviderSdkImports:
    FORBIDDEN_IMPORTS = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
    )

    def test_gemini_module_has_no_provider_imports(self) -> None:
        import app.providers.gemini as mod

        source = Path(mod.__file__).read_text()  # type: ignore[arg-type]
        for pattern in self.FORBIDDEN_IMPORTS:
            assert pattern not in source, f"Found '{pattern}' in gemini.py"
