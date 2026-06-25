from __future__ import annotations

import gzip
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.observability.capture import CaptureError, EventCaptureReader, EventCaptureWriter
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
    started_at: datetime | None = None,
) -> SessionCapture:
    return SessionCapture(
        session_id=session_id or uuid.uuid4().hex,
        run_id=1,
        wave="P3 – Services & Profiles",
        issue_number=42,
        role=SessionRole.IMPLEMENTOR,
        skill="implement",
        model="claude-sonnet-4-6",
        started_at=started_at or datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 6, 15, 10, 25, 0, tzinfo=UTC),
        events=[
            NormalisedEvent(
                kind=EventKind.TOOL_CALL,
                content="",
                tool_name="Edit",
                tool_input='{"file": "main.py"}',
                timestamp=1750068000.0,
            ),
            NormalisedEvent(
                kind=EventKind.OUTPUT,
                content="Done implementing the feature.",
                timestamp=1750069500.0,
            ),
        ],
        usage=UsageReport(
            tokens_in=12000,
            tokens_out=4500,
            cost_usd=0.085,
            model="claude-sonnet-4-6",
            duration_seconds=1500.0,
        ),
        audit_log=[
            AuditRecord(
                tool_name="Edit",
                tool_input={"file": "main.py"},
                blocked=False,
                timestamp=1750068000.0,
            ),
        ],
        outcome=SessionOutcome.COMPLETED,
        artifacts=["main.py", "tests/test_main.py"],
        retry_count=1,
    )


class TestRoundTrip:
    def test_write_and_read_back(self, tmp_path: Path) -> None:
        capture = _make_capture(session_id="abc123")
        writer = EventCaptureWriter(tmp_path)
        reader = EventCaptureReader(tmp_path)

        dest = writer.write(capture)
        assert dest.exists()
        assert dest.suffix == ".gz"

        restored = reader.read("abc123", "2026-06")
        assert restored == capture

    def test_all_aggregation_keys_present(self, tmp_path: Path) -> None:
        capture = _make_capture()
        writer = EventCaptureWriter(tmp_path)
        dest = writer.write(capture)

        with gzip.open(dest, "rb") as f:
            raw = f.read()

        import json

        data = json.loads(raw)
        for key in ("session_id", "run_id", "wave", "issue_number", "role", "skill", "model"):
            assert key in data, f"Missing aggregation key: {key}"

    def test_file_is_gzip_compressed(self, tmp_path: Path) -> None:
        capture = _make_capture()
        writer = EventCaptureWriter(tmp_path)
        dest = writer.write(capture)

        raw_bytes = dest.read_bytes()
        assert raw_bytes[:2] == b"\x1f\x8b"  # gzip magic number

        uncompressed = gzip.decompress(raw_bytes)
        assert len(uncompressed) > len(raw_bytes)


class TestDirectoryStructure:
    def test_month_directory_created(self, tmp_path: Path) -> None:
        capture = _make_capture(
            started_at=datetime(2026, 3, 10, tzinfo=UTC),
        )
        writer = EventCaptureWriter(tmp_path)
        writer.write(capture)

        month_dir = tmp_path / "captures" / "2026-03"
        assert month_dir.is_dir()

    def test_different_months_get_different_dirs(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)

        c1 = _make_capture(
            session_id="s1",
            started_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        c2 = _make_capture(
            session_id="s2",
            started_at=datetime(2026, 2, 15, tzinfo=UTC),
        )
        writer.write(c1)
        writer.write(c2)

        assert (tmp_path / "captures" / "2026-01" / "s1.json.gz").exists()
        assert (tmp_path / "captures" / "2026-02" / "s2.json.gz").exists()


class TestReader:
    def test_list_sessions(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)
        reader = EventCaptureReader(tmp_path)

        for sid in ("aaa", "bbb", "ccc"):
            writer.write(_make_capture(session_id=sid))

        sessions = reader.list_sessions("2026-06")
        assert sessions == ["aaa", "bbb", "ccc"]

    def test_list_sessions_empty_month(self, tmp_path: Path) -> None:
        reader = EventCaptureReader(tmp_path)
        assert reader.list_sessions("2099-01") == []

    def test_list_months(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)
        reader = EventCaptureReader(tmp_path)

        for month_num, sid in [(1, "s1"), (3, "s2"), (6, "s3")]:
            writer.write(
                _make_capture(
                    session_id=sid,
                    started_at=datetime(2026, month_num, 1, tzinfo=UTC),
                )
            )

        months = reader.list_months()
        assert months == ["2026-01", "2026-03", "2026-06"]

    def test_list_months_empty(self, tmp_path: Path) -> None:
        reader = EventCaptureReader(tmp_path)
        assert reader.list_months() == []

    def test_read_missing_session_raises(self, tmp_path: Path) -> None:
        reader = EventCaptureReader(tmp_path)
        with pytest.raises(CaptureError, match="not found"):
            reader.read("nonexistent", "2026-06")


class TestErrorHandling:
    def test_write_to_unwritable_dir_raises(self, tmp_path: Path) -> None:
        read_only = tmp_path / "locked"
        read_only.mkdir()
        read_only.chmod(0o444)

        capture = _make_capture()
        writer = EventCaptureWriter(read_only)

        with pytest.raises(CaptureError, match="Failed to write"):
            writer.write(capture)

        read_only.chmod(0o755)

    def test_read_corrupted_file_raises(self, tmp_path: Path) -> None:
        month_dir = tmp_path / "captures" / "2026-06"
        month_dir.mkdir(parents=True)
        corrupt_file = month_dir / "bad.json.gz"
        corrupt_file.write_bytes(b"not gzip data")

        reader = EventCaptureReader(tmp_path)
        with pytest.raises(CaptureError, match="Failed to read"):
            reader.read("bad", "2026-06")
