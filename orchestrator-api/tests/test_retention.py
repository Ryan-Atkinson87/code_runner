from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.observability.capture import EventCaptureWriter
from app.observability.models import SessionCapture
from app.observability.retention import (
    _BYTES_PER_GB,
    ObservabilityPruner,
    PruneResult,
    RetentionPolicy,
    _month_last_day,
)
from app.providers.types import SessionOutcome, SessionRole, UsageReport


def _capture(
    session_id: str | None = None,
    started_at: datetime | None = None,
) -> SessionCapture:
    dt = started_at or datetime(2026, 6, 15, tzinfo=UTC)
    return SessionCapture(
        session_id=session_id or uuid.uuid4().hex,
        run_id=1,
        wave="P6",
        issue_number=49,
        role=SessionRole.IMPLEMENTOR,
        skill="implement",
        model="claude-sonnet-4-6",
        started_at=dt,
        finished_at=dt,
        usage=UsageReport(
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            model="claude-sonnet-4-6",
            duration_seconds=10.0,
        ),
        outcome=SessionOutcome.COMPLETED,
    )


def _write_month(tmp_path: Path, year: int, month: int, sid: str) -> None:
    dt = datetime(year, month, 1, tzinfo=UTC)
    EventCaptureWriter(tmp_path).write(_capture(session_id=sid, started_at=dt))


class TestRetentionPolicyDefaults:
    def test_defaults_match_spec(self) -> None:
        p = RetentionPolicy()
        assert p.cap_bytes == 50 * _BYTES_PER_GB
        assert p.raw_days == 90
        assert p.traces_days == 180

    def test_configurable(self) -> None:
        p = RetentionPolicy(cap_bytes=1024, raw_days=30, traces_days=60)
        assert p.cap_bytes == 1024
        assert p.raw_days == 30
        assert p.traces_days == 60


class TestMonthLastDay:
    def test_june_ends_on_30th(self) -> None:
        from datetime import date

        assert _month_last_day("2026-06") == date(2026, 6, 30)

    def test_february_non_leap(self) -> None:
        from datetime import date

        assert _month_last_day("2026-02") == date(2026, 2, 28)

    def test_february_leap(self) -> None:
        from datetime import date

        assert _month_last_day("2024-02") == date(2024, 2, 29)

    def test_december_ends_on_31st(self) -> None:
        from datetime import date

        assert _month_last_day("2026-12") == date(2026, 12, 31)


class TestNoPruningWhenNoCapturesDir:
    def test_empty_base_dir_returns_empty_result(self, tmp_path: Path) -> None:
        result = ObservabilityPruner().prune(tmp_path, RetentionPolicy())
        assert result == PruneResult()


class TestAgePruning:
    def test_old_month_is_deleted(self, tmp_path: Path) -> None:
        # 2026-01 last day = 2026-01-31; today = 2026-10-01 → 243 days > 90
        _write_month(tmp_path, 2026, 1, "old")
        now = datetime(2026, 10, 1, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert "2026-01" in result.months_deleted
        assert result.files_deleted == 1
        assert result.bytes_freed > 0
        assert not (tmp_path / "captures" / "2026-01").exists()

    def test_recent_month_is_kept(self, tmp_path: Path) -> None:
        # 2026-06 last day = 2026-06-30; today = 2026-08-01 → 32 days ≤ 90
        _write_month(tmp_path, 2026, 6, "recent")
        now = datetime(2026, 8, 1, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert result.months_deleted == []
        assert (tmp_path / "captures" / "2026-06" / "recent.json.gz").exists()

    def test_month_at_exact_boundary_is_kept(self, tmp_path: Path) -> None:
        # 2026-06 last day = 2026-06-30; today = 2026-09-28 → 90 days exactly → NOT pruned
        _write_month(tmp_path, 2026, 6, "boundary")
        now = datetime(2026, 9, 28, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert "2026-06" not in result.months_deleted

    def test_month_one_day_past_boundary_is_pruned(self, tmp_path: Path) -> None:
        # 2026-06 last day = 2026-06-30; today = 2026-09-29 → 91 days > 90 → pruned
        _write_month(tmp_path, 2026, 6, "past")
        now = datetime(2026, 9, 29, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert "2026-06" in result.months_deleted

    def test_mixed_months_only_old_deleted(self, tmp_path: Path) -> None:
        # today = 2026-10-01; 2026-01 is old (>90d), 2026-09 is recent (<90d)
        _write_month(tmp_path, 2026, 1, "old")
        _write_month(tmp_path, 2026, 9, "new")
        now = datetime(2026, 10, 1, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert "2026-01" in result.months_deleted
        assert "2026-09" not in result.months_deleted
        assert (tmp_path / "captures" / "2026-09" / "new.json.gz").exists()


class TestCapPruning:
    def test_oldest_first_when_over_cap(self, tmp_path: Path) -> None:
        # All months recent (within retention), cap=1 byte forces all to be pruned oldest first
        now = datetime(2026, 6, 15, tzinfo=UTC)
        _write_month(tmp_path, 2026, 3, "oldest")
        _write_month(tmp_path, 2026, 4, "middle")
        _write_month(tmp_path, 2026, 5, "newest")
        policy = RetentionPolicy(raw_days=90, cap_bytes=1)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert result.months_deleted[0] == "2026-03"
        assert result.months_deleted[1] == "2026-04"
        assert result.months_deleted[2] == "2026-05"

    def test_stops_when_under_cap(self, tmp_path: Path) -> None:
        # 3 months all within retention; set cap to just above 2-file size → delete 1 oldest
        now = datetime(2026, 6, 15, tzinfo=UTC)
        _write_month(tmp_path, 2026, 3, "oldest")
        _write_month(tmp_path, 2026, 4, "middle")
        _write_month(tmp_path, 2026, 5, "newest")

        captures_dir = tmp_path / "captures"
        total_size = sum(f.stat().st_size for f in captures_dir.rglob("*.json.gz"))
        # Allow 2 files' worth — deletes the 1 oldest month
        single_file_size = total_size // 3
        cap = total_size - single_file_size + 1

        policy = RetentionPolicy(raw_days=90, cap_bytes=cap)
        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert "2026-03" in result.months_deleted
        assert (captures_dir / "2026-05" / "newest.json.gz").exists()

    def test_no_cap_pruning_when_under_cap(self, tmp_path: Path) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        _write_month(tmp_path, 2026, 5, "s1")
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert result.months_deleted == []
        assert result.bytes_freed == 0

    def test_files_deleted_count_is_accurate(self, tmp_path: Path) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        writer = EventCaptureWriter(tmp_path)
        for sid in ("a", "b", "c"):
            writer.write(_capture(session_id=sid, started_at=datetime(2026, 3, 1, tzinfo=UTC)))

        policy = RetentionPolicy(raw_days=90, cap_bytes=1)
        result = ObservabilityPruner().prune(tmp_path, policy, now)

        assert result.files_deleted == 3


class TestRollupsNeverPruned:
    def test_pruner_does_not_touch_sqlite(self, tmp_path: Path) -> None:
        # Simulate a SQLite rollup file sitting next to captures/
        db_file = tmp_path / "state.db"
        db_file.write_bytes(b"fake-sqlite-content")
        now = datetime(2026, 10, 1, tzinfo=UTC)

        # Write an old capture month that WILL be pruned
        _write_month(tmp_path, 2026, 1, "old")
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        ObservabilityPruner().prune(tmp_path, policy, now)

        # captures/ month is gone but state.db is untouched
        assert not (tmp_path / "captures" / "2026-01").exists()
        assert db_file.exists()
        assert db_file.read_bytes() == b"fake-sqlite-content"

    def test_pruner_does_not_touch_dirs_outside_captures(self, tmp_path: Path) -> None:
        other_dir = tmp_path / "git-repos" / "my-project"
        other_dir.mkdir(parents=True)
        (other_dir / "README.md").write_text("important file")
        now = datetime(2026, 10, 1, tzinfo=UTC)

        _write_month(tmp_path, 2026, 1, "old")
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        ObservabilityPruner().prune(tmp_path, policy, now)

        assert (other_dir / "README.md").exists()


class TestIdempotency:
    def test_rerun_after_full_prune_is_no_op(self, tmp_path: Path) -> None:
        _write_month(tmp_path, 2026, 1, "old")
        now = datetime(2026, 10, 1, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        pruner = ObservabilityPruner()
        first = pruner.prune(tmp_path, policy, now)
        second = pruner.prune(tmp_path, policy, now)

        assert "2026-01" in first.months_deleted
        assert second.months_deleted == []
        assert second.errors == []

    def test_prune_with_no_captures_dir_is_no_op(self, tmp_path: Path) -> None:
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)
        result = ObservabilityPruner().prune(tmp_path, policy)
        assert result == PruneResult()

    def test_bytes_freed_is_consistent_across_runs(self, tmp_path: Path) -> None:
        _write_month(tmp_path, 2026, 1, "old")
        now = datetime(2026, 10, 1, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, cap_bytes=10 * _BYTES_PER_GB)

        pruner = ObservabilityPruner()
        first = pruner.prune(tmp_path, policy, now)
        second = pruner.prune(tmp_path, policy, now)

        assert first.bytes_freed > 0
        assert second.bytes_freed == 0


class TestPruneResult:
    def test_default_empty(self) -> None:
        r = PruneResult()
        assert r.months_deleted == []
        assert r.files_deleted == 0
        assert r.bytes_freed == 0
        assert r.errors == []
