"""Unit tests for the Gemini CLI adapter using recorded JSONL fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from app.providers.gemini import GeminiAdapter, _is_blocked, _map_status, _parse_output
from app.providers.types import EventKind, SessionOutcome


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
