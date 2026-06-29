from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.db.migrations import ALL_MIGRATIONS
from app.observability.capture import EventCaptureWriter
from app.observability.models import SessionCapture
from app.observability.rollup import RollupStore
from app.providers.types import SessionOutcome, SessionRole, UsageReport


def _init_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    for migration_cls in ALL_MIGRATIONS:
        m = migration_cls()
        m.apply(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
            (m.version, m.description),
        )
    conn.commit()
    return conn


def _capture(
    *,
    session_id: str | None = None,
    wave: str = "P6",
    issue_number: int = 47,
    role: SessionRole = SessionRole.IMPLEMENTOR,
    skill: str = "implement",
    model: str = "claude-sonnet-4-6",
    month_dt: datetime | None = None,
    tokens_in: int = 1000,
    tokens_out: int = 500,
    cost_usd: float = 0.01,
    duration_seconds: float = 60.0,
    retry_count: int = 0,
    outcome: SessionOutcome = SessionOutcome.COMPLETED,
) -> SessionCapture:
    dt = month_dt or datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)
    return SessionCapture(
        session_id=session_id or uuid.uuid4().hex,
        run_id=1,
        wave=wave,
        issue_number=issue_number,
        role=role,
        skill=skill,
        model=model,
        started_at=dt,
        finished_at=dt,
        usage=UsageReport(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            model=model,
            duration_seconds=duration_seconds,
        ),
        outcome=outcome,
        retry_count=retry_count,
    )


class TestAggregateSingleSession:
    def test_returns_true_on_first_aggregate(self) -> None:
        store = RollupStore(_init_conn())
        assert store.aggregate_session(_capture()) is True

    def test_returns_false_on_duplicate(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        cap = _capture(session_id="fixed-id")
        store.aggregate_session(cap)
        assert store.aggregate_session(cap) is False

    def test_rollup_row_created(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(tokens_in=2000, tokens_out=800))

        rows = store.query()
        assert len(rows) == 1
        assert rows[0].tokens_in == 2000
        assert rows[0].tokens_out == 800

    def test_outcome_counters_completed(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(outcome=SessionOutcome.COMPLETED))
        row = store.query()[0]
        assert row.completed_count == 1
        assert row.blocked_count == 0
        assert row.error_count == 0

    def test_outcome_counters_blocked(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(outcome=SessionOutcome.BLOCKED))
        row = store.query()[0]
        assert row.completed_count == 0
        assert row.blocked_count == 1
        assert row.error_count == 0

    def test_outcome_counters_error(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(outcome=SessionOutcome.ERROR))
        row = store.query()[0]
        assert row.completed_count == 0
        assert row.blocked_count == 0
        assert row.error_count == 1

    def test_retry_count_accumulated(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(session_id="s1", retry_count=2))
        store.aggregate_session(_capture(session_id="s2", retry_count=1))
        row = store.query()[0]
        assert row.retry_count == 3


class TestIdempotency:
    def test_double_aggregate_does_not_double_count(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        cap = _capture(session_id="idem", tokens_in=500, tokens_out=200)
        store.aggregate_session(cap)
        store.aggregate_session(cap)

        row = store.query()[0]
        assert row.session_count == 1
        assert row.tokens_in == 500
        assert row.tokens_out == 200

    def test_aggregate_from_reader_is_idempotent(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)
        cap = _capture(session_id="r1", tokens_in=300, tokens_out=100)
        writer.write(cap)

        from app.observability.capture import EventCaptureReader

        reader = EventCaptureReader(tmp_path)
        conn = _init_conn()
        store = RollupStore(conn)

        first = store.aggregate_from_reader(reader, "2026-06")
        second = store.aggregate_from_reader(reader, "2026-06")

        assert first == 1
        assert second == 0

        row = store.query()[0]
        assert row.session_count == 1
        assert row.tokens_in == 300

    def test_partial_rerun_only_adds_new_sessions(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)
        cap_a = _capture(session_id="a1", tokens_in=100)
        cap_b = _capture(session_id="b1", tokens_in=200)
        writer.write(cap_a)

        from app.observability.capture import EventCaptureReader

        reader = EventCaptureReader(tmp_path)
        conn = _init_conn()
        store = RollupStore(conn)

        store.aggregate_from_reader(reader, "2026-06")
        writer.write(cap_b)
        newly = store.aggregate_from_reader(reader, "2026-06")

        assert newly == 1
        row = store.query()[0]
        assert row.session_count == 2
        assert row.tokens_in == 300


class TestRollupsAccumulate:
    def test_multiple_sessions_same_dimension_accumulate(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        for i in range(3):
            store.aggregate_session(_capture(session_id=f"s{i}", tokens_in=1000, tokens_out=400))
        row = store.query()[0]
        assert row.session_count == 3
        assert row.tokens_in == 3000
        assert row.tokens_out == 1200

    def test_different_dimensions_create_separate_rows(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(_capture(session_id="s1", issue_number=10))
        store.aggregate_session(_capture(session_id="s2", issue_number=20))

        rows = store.query()
        assert len(rows) == 2
        issue_nums = {r.issue_number for r in rows}
        assert issue_nums == {10, 20}

    def test_different_months_create_separate_rows(self) -> None:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(
            _capture(session_id="m1", month_dt=datetime(2026, 5, 1, tzinfo=UTC))
        )
        store.aggregate_session(
            _capture(session_id="m2", month_dt=datetime(2026, 6, 1, tzinfo=UTC))
        )
        rows = store.query()
        assert len(rows) == 2
        months = {r.month for r in rows}
        assert months == {"2026-05", "2026-06"}


class TestQueryFilters:
    def _populate(self) -> RollupStore:
        conn = _init_conn()
        store = RollupStore(conn)
        store.aggregate_session(
            _capture(
                session_id="a",
                wave="P6",
                issue_number=47,
                role=SessionRole.IMPLEMENTOR,
                skill="implement",
            )
        )  # noqa: E501
        store.aggregate_session(
            _capture(
                session_id="b",
                wave="P6",
                issue_number=48,
                role=SessionRole.IMPLEMENTOR,
                skill="implement",
            )
        )  # noqa: E501
        store.aggregate_session(
            _capture(
                session_id="c",
                wave="P6",
                issue_number=47,
                role=SessionRole.ORCHESTRATOR,
                skill="review",
            )
        )  # noqa: E501
        store.aggregate_session(
            _capture(
                session_id="d",
                wave="P7",
                issue_number=47,
                role=SessionRole.IMPLEMENTOR,
                skill="implement",
                month_dt=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )  # noqa: E501
        return store

    def test_filter_by_issue(self) -> None:
        store = self._populate()
        rows = store.query(issue_number=47)
        assert all(r.issue_number == 47 for r in rows)
        assert len(rows) == 3

    def test_filter_by_wave(self) -> None:
        store = self._populate()
        rows = store.query(wave="P7")
        assert len(rows) == 1
        assert rows[0].wave == "P7"

    def test_filter_by_role(self) -> None:
        store = self._populate()
        rows = store.query(role="orchestrator")
        assert len(rows) == 1
        assert rows[0].skill == "review"

    def test_filter_by_skill(self) -> None:
        store = self._populate()
        rows = store.query(skill="implement")
        assert all(r.skill == "implement" for r in rows)
        assert len(rows) == 3

    def test_filter_by_month(self) -> None:
        store = self._populate()
        rows = store.query(month="2026-06")
        assert len(rows) == 3

    def test_combined_filters(self) -> None:
        store = self._populate()
        rows = store.query(wave="P6", issue_number=47, role="implementor")
        assert len(rows) == 1
        assert rows[0].skill == "implement"

    def test_no_filters_returns_all(self) -> None:
        store = self._populate()
        rows = store.query()
        assert len(rows) == 4


class TestAggregateFromReader:
    def test_returns_count_of_sessions_processed(self, tmp_path: Path) -> None:
        writer = EventCaptureWriter(tmp_path)
        for i in range(4):
            writer.write(_capture(session_id=f"s{i}"))

        from app.observability.capture import EventCaptureReader

        reader = EventCaptureReader(tmp_path)
        conn = _init_conn()
        store = RollupStore(conn)
        count = store.aggregate_from_reader(reader, "2026-06")
        assert count == 4

    def test_skips_missing_month(self, tmp_path: Path) -> None:
        from app.observability.capture import EventCaptureReader

        reader = EventCaptureReader(tmp_path)
        conn = _init_conn()
        store = RollupStore(conn)
        count = store.aggregate_from_reader(reader, "2099-01")
        assert count == 0
        assert store.query() == []
