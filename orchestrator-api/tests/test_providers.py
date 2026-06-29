from __future__ import annotations

from pathlib import Path

import pytest

from app.providers import (
    EventKind,
    NormalisedEvent,
    ProviderAdapter,
    SessionOutcome,
    SessionResult,
    SessionRole,
    UsageReport,
)


class TestProviderAdapterCannotBeInstantiated:
    def test_direct_instantiation_raises(self) -> None:
        with pytest.raises(TypeError):
            ProviderAdapter()  # type: ignore[abstract]


class TestFakeAdapterSatisfiesInterface:
    """A trivial fake adapter proving the interface is implementable."""

    def test_fake_adapter_is_provider_adapter(self) -> None:
        class FakeAdapter(ProviderAdapter):
            async def run_session(
                self,
                workdir: Path,
                role: SessionRole,
                model: str,
                allowed_tools: list[str],
                prompt: str,
                context_files: list[Path],
            ) -> SessionResult:
                return SessionResult(outcome=SessionOutcome.COMPLETED)

        adapter = FakeAdapter()
        assert isinstance(adapter, ProviderAdapter)

    def test_fake_adapter_returns_session_result(self, tmp_path: Path) -> None:
        class FakeAdapter(ProviderAdapter):
            async def run_session(
                self,
                workdir: Path,
                role: SessionRole,
                model: str,
                allowed_tools: list[str],
                prompt: str,
                context_files: list[Path],
            ) -> SessionResult:
                return SessionResult(
                    events=[
                        NormalisedEvent(kind=EventKind.OUTPUT, content="done"),
                    ],
                    usage=UsageReport(
                        tokens_in=100,
                        tokens_out=50,
                        cost_usd=0.01,
                        model="fake-model",
                        duration_seconds=1.5,
                    ),
                    outcome=SessionOutcome.COMPLETED,
                    artifacts=["src/main.py"],
                )

        import asyncio

        adapter = FakeAdapter()
        result = asyncio.run(
            adapter.run_session(
                workdir=tmp_path,
                role=SessionRole.IMPLEMENTOR,
                model="fake-model",
                allowed_tools=["Read", "Write"],
                prompt="Fix the bug",
                context_files=[tmp_path / "issue.md"],
            )
        )
        assert result.outcome == SessionOutcome.COMPLETED
        assert len(result.events) == 1
        assert result.events[0].kind == EventKind.OUTPUT
        assert result.usage.tokens_in == 100
        assert result.artifacts == ["src/main.py"]


class TestSessionRole:
    def test_orchestrator_value(self) -> None:
        assert SessionRole.ORCHESTRATOR == "orchestrator"

    def test_implementor_value(self) -> None:
        assert SessionRole.IMPLEMENTOR == "implementor"

    def test_constrained_to_two_values(self) -> None:
        assert len(SessionRole) == 2


class TestSessionOutcome:
    def test_completed_value(self) -> None:
        assert SessionOutcome.COMPLETED == "completed"

    def test_blocked_value(self) -> None:
        assert SessionOutcome.BLOCKED == "blocked"

    def test_error_value(self) -> None:
        assert SessionOutcome.ERROR == "error"

    def test_constrained_to_three_values(self) -> None:
        assert len(SessionOutcome) == 3


class TestEventKind:
    def test_four_event_kinds(self) -> None:
        assert len(EventKind) == 4
        assert set(EventKind) == {
            EventKind.REASONING,
            EventKind.TOOL_CALL,
            EventKind.TOOL_RESULT,
            EventKind.OUTPUT,
        }


class TestNormalisedEvent:
    def test_minimal_event(self) -> None:
        event = NormalisedEvent(kind=EventKind.REASONING, content="thinking...")
        assert event.kind == EventKind.REASONING
        assert event.tool_name is None
        assert event.tool_input is None

    def test_tool_call_event(self) -> None:
        event = NormalisedEvent(
            kind=EventKind.TOOL_CALL,
            tool_name="Read",
            tool_input='{"file": "main.py"}',
        )
        assert event.tool_name == "Read"
        assert event.tool_input == '{"file": "main.py"}'


class TestUsageReport:
    def test_defaults(self) -> None:
        report = UsageReport()
        assert report.tokens_in == 0
        assert report.tokens_out == 0
        assert report.cost_usd == 0.0
        assert report.model == ""
        assert report.duration_seconds == 0.0

    def test_populated(self) -> None:
        report = UsageReport(
            tokens_in=5000,
            tokens_out=2000,
            cost_usd=0.05,
            model="claude-sonnet-4-6",
            duration_seconds=45.2,
        )
        assert report.tokens_in == 5000
        assert report.cost_usd == 0.05


class TestSessionResult:
    def test_minimal_result(self) -> None:
        result = SessionResult(outcome=SessionOutcome.ERROR)
        assert result.events == []
        assert result.artifacts == []
        assert result.usage.tokens_in == 0

    def test_outcome_is_required(self) -> None:
        with pytest.raises(ValueError):
            SessionResult()  # type: ignore[call-arg]


class TestNoProviderSdkImports:
    """Verify that neither module imports any provider SDK."""

    FORBIDDEN_IMPORTS = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
    )

    def test_types_module_has_no_provider_imports(self) -> None:
        import app.providers.types as mod

        source = Path(mod.__file__).read_text()  # type: ignore[arg-type]
        for pattern in self.FORBIDDEN_IMPORTS:
            assert pattern not in source, f"Found '{pattern}' in types.py"

    def test_adapter_module_has_no_provider_imports(self) -> None:
        import app.providers.adapter as mod

        source = Path(mod.__file__).read_text()  # type: ignore[arg-type]
        for pattern in self.FORBIDDEN_IMPORTS:
            assert pattern not in source, f"Found '{pattern}' in adapter.py"
