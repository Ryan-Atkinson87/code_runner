from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.observability.models import SessionCapture
from app.providers.types import (
    AuditRecord,
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionRole,
    UsageReport,
)


def _make_capture(
    *,
    session_id: str | None = None,
    outcome: SessionOutcome = SessionOutcome.COMPLETED,
    wave: str = "P6 – Observability",
    issue_number: int = 47,
    skill: str = "implement",
    role: SessionRole = SessionRole.IMPLEMENTOR,
) -> SessionCapture:
    return SessionCapture(
        session_id=session_id or uuid.uuid4().hex,
        run_id=1,
        wave=wave,
        issue_number=issue_number,
        role=role,
        skill=skill,
        model="claude-sonnet-4-6",
        started_at=datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 6, 15, 10, 30, 0, tzinfo=UTC),
        events=[
            NormalisedEvent(kind=EventKind.OUTPUT, content="Done.", timestamp=1750068000.0),
        ],
        usage=UsageReport(
            tokens_in=5000,
            tokens_out=2000,
            cost_usd=0.05,
            model="claude-sonnet-4-6",
            duration_seconds=1800.0,
        ),
        audit_log=[
            AuditRecord(tool_name="Edit", tool_input={"file": "main.py"}, timestamp=1750068000.0),
        ],
        outcome=outcome,
        artifacts=["main.py"],
        retry_count=0,
    )


def _make_emitter(mock_client: MagicMock) -> object:
    """Return a LangfuseEmitter with a mocked Langfuse client."""
    from app.observability.langfuse_emitter import LangfuseEmitter

    with patch("app.observability.langfuse_emitter.Langfuse", return_value=mock_client):
        return LangfuseEmitter(public_key="pk-test", secret_key="sk-test", host="http://lf:3000")


class TestTraceShape:
    def test_emits_trace_with_session_id(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.return_value = MagicMock()
        emitter = _make_emitter(mock_client)
        capture = _make_capture(session_id="abc123")

        emitter.emit(capture)  # type: ignore[attr-defined]

        mock_client.trace.assert_called_once()
        assert mock_client.trace.call_args[1]["id"] == "abc123"

    def test_trace_name_encodes_role_and_skill(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.return_value = MagicMock()
        emitter = _make_emitter(mock_client)
        capture = _make_capture(role=SessionRole.ORCHESTRATOR, skill="review")

        emitter.emit(capture)  # type: ignore[attr-defined]

        name = mock_client.trace.call_args[1]["name"]
        assert "orchestrator" in name
        assert "review" in name

    def test_metadata_contains_all_dimensions(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.return_value = MagicMock()
        emitter = _make_emitter(mock_client)
        capture = _make_capture(wave="P6 – Obs", issue_number=47, skill="implement")

        emitter.emit(capture)  # type: ignore[attr-defined]

        metadata = mock_client.trace.call_args[1]["metadata"]
        assert metadata["wave"] == "P6 – Obs"
        assert metadata["issue_number"] == 47
        assert metadata["role"] == "implementor"
        assert metadata["skill"] == "implement"
        assert metadata["model"] == "claude-sonnet-4-6"
        assert metadata["outcome"] == "completed"
        assert metadata["month"] == "2026-06"

    def test_tags_include_wave_issue_and_month(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.return_value = MagicMock()
        emitter = _make_emitter(mock_client)
        capture = _make_capture(wave="P6 – Observability", issue_number=47)

        emitter.emit(capture)  # type: ignore[attr-defined]

        tags: list[str] = mock_client.trace.call_args[1]["tags"]
        joined = " ".join(tags)
        assert "issue:47" in joined
        assert "P6" in joined
        assert "2026-06" in joined

    def test_generation_span_carries_token_counts(self) -> None:
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace
        emitter = _make_emitter(mock_client)
        capture = _make_capture()

        emitter.emit(capture)  # type: ignore[attr-defined]

        mock_trace.generation.assert_called_once()
        gen_kwargs = mock_trace.generation.call_args[1]
        usage = gen_kwargs["usage"]
        assert usage["input"] == 5000
        assert usage["output"] == 2000
        assert gen_kwargs["model"] == "claude-sonnet-4-6"

    def test_flush_called_after_trace(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.return_value = MagicMock()
        emitter = _make_emitter(mock_client)
        capture = _make_capture()

        emitter.emit(capture)  # type: ignore[attr-defined]

        mock_client.flush.assert_called_once()


class TestDegradation:
    def test_trace_failure_is_logged_not_raised(self) -> None:
        mock_client = MagicMock()
        mock_client.trace.side_effect = RuntimeError("Langfuse unreachable")
        emitter = _make_emitter(mock_client)
        capture = _make_capture()

        # Must not raise
        emitter.emit(capture)  # type: ignore[attr-defined]

    def test_generation_failure_is_logged_not_raised(self) -> None:
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_trace.generation.side_effect = ValueError("Bad generation params")
        mock_client.trace.return_value = mock_trace
        emitter = _make_emitter(mock_client)
        capture = _make_capture()

        emitter.emit(capture)  # type: ignore[attr-defined]

    def test_flush_failure_is_logged_not_raised(self) -> None:
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_client.flush.side_effect = TimeoutError("Flush timeout")
        emitter = _make_emitter(mock_client)
        capture = _make_capture()

        emitter.emit(capture)  # type: ignore[attr-defined]

    def test_multiple_emits_independent(self) -> None:
        """A failed emit must not prevent the next one from being attempted."""
        mock_client = MagicMock()
        call_count = 0

        def flaky_trace(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First call fails")
            return MagicMock()

        mock_client.trace.side_effect = flaky_trace
        emitter = _make_emitter(mock_client)

        emitter.emit(_make_capture(session_id="s1"))  # type: ignore[attr-defined]
        emitter.emit(_make_capture(session_id="s2"))  # type: ignore[attr-defined]

        assert mock_client.trace.call_count == 2


class TestFromEnv:
    def test_from_env_reads_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pub-key")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sec-key")
        monkeypatch.setenv("LANGFUSE_HOST", "http://custom:3000")

        mock_client = MagicMock()
        with patch(
            "app.observability.langfuse_emitter.Langfuse", return_value=mock_client
        ) as mock_cls:
            from app.observability.langfuse_emitter import LangfuseEmitter

            LangfuseEmitter.from_env()

        mock_cls.assert_called_once_with(
            public_key="pub-key",
            secret_key="sec-key",
            host="http://custom:3000",
        )

    def test_from_env_uses_default_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)

        with patch("app.observability.langfuse_emitter.Langfuse") as mock_cls:
            from app.observability.langfuse_emitter import LangfuseEmitter

            LangfuseEmitter.from_env()

        assert mock_cls.call_args[1]["host"] == "http://langfuse:3000"
