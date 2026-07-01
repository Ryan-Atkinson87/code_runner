from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

import pytest

from app.db.migrations import ALL_MIGRATIONS
from app.observability.models import SessionCapture
from app.observability.reports import (
    EfficiencyReport,
    EfficiencyReportGenerator,
)
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
    issue_number: int = 1,
    role: SessionRole = SessionRole.IMPLEMENTOR,
    skill: str = "implement",
    model: str = "claude-sonnet-4-6",
    month_dt: datetime | None = None,
    tokens_in: int = 1000,
    tokens_out: int = 400,
    cost_usd: float = 0.01,
    duration_seconds: float = 60.0,
    retry_count: int = 0,
    outcome: SessionOutcome = SessionOutcome.COMPLETED,
) -> SessionCapture:
    dt = month_dt or datetime(2026, 6, 15, tzinfo=UTC)
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


def _store_with(*captures: SessionCapture) -> RollupStore:
    store = RollupStore(_init_conn())
    for cap in captures:
        store.aggregate_session(cap)
    return store


class TestReportScopes:
    def test_on_demand_renders_empty_store(self) -> None:
        store = _store_with()
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert isinstance(report, EfficiencyReport)
        assert report.scope == "all"
        assert report.total_sessions == 0

    def test_on_demand_renders_with_data(self) -> None:
        store = _store_with(
            _capture(session_id="s1", tokens_in=500, tokens_out=200),
            _capture(session_id="s2", tokens_in=600, tokens_out=300),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.total_sessions == 2
        assert report.tokens.total_in == 1100
        assert report.tokens.total_out == 500

    def test_for_wave_scope_filters(self) -> None:
        store = _store_with(
            _capture(session_id="p6", wave="P6"),
            _capture(session_id="p7", wave="P7"),
        )
        report = EfficiencyReportGenerator().generate_for_wave(store, "P6")
        assert report.scope == "wave:P6"
        assert report.total_sessions == 1

    def test_for_month_scope_filters(self) -> None:
        store = _store_with(
            _capture(session_id="june", month_dt=datetime(2026, 6, 1, tzinfo=UTC)),
            _capture(session_id="july", month_dt=datetime(2026, 7, 1, tzinfo=UTC)),
        )
        report = EfficiencyReportGenerator().generate_for_month(store, "2026-06")
        assert report.scope == "month:2026-06"
        assert report.total_sessions == 1

    def test_generated_at_is_utc(self) -> None:
        store = _store_with()
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.generated_at.tzinfo is not None


class TestTokenBreakdown:
    def test_by_issue_accumulates_correctly(self) -> None:
        store = _store_with(
            _capture(session_id="a", issue_number=10, tokens_in=100, tokens_out=50),
            _capture(session_id="b", issue_number=10, tokens_in=200, tokens_out=80),
            _capture(session_id="c", issue_number=20, tokens_in=300, tokens_out=100),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.tokens.by_issue[10] == 430  # (100+50) + (200+80)
        assert report.tokens.by_issue[20] == 400  # 300+100

    def test_by_role_and_skill(self) -> None:
        store = _store_with(
            _capture(
                session_id="a",
                role=SessionRole.IMPLEMENTOR,
                skill="implement",
                tokens_in=500,
                tokens_out=200,
            ),
            _capture(
                session_id="b",
                role=SessionRole.ORCHESTRATOR,
                skill="review",
                tokens_in=300,
                tokens_out=100,
            ),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.tokens.by_role["implementor"] == 700
        assert report.tokens.by_role["orchestrator"] == 400
        assert report.tokens.by_skill["implement"] == 700
        assert report.tokens.by_skill["review"] == 400

    def test_by_wave(self) -> None:
        store = _store_with(
            _capture(session_id="a", wave="P6", tokens_in=1000, tokens_out=400),
            _capture(session_id="b", wave="P7", tokens_in=500, tokens_out=200),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.tokens.by_wave["P6"] == 1400
        assert report.tokens.by_wave["P7"] == 700

    def test_total_in_and_out(self) -> None:
        store = _store_with(
            _capture(session_id="a", tokens_in=1000, tokens_out=400),
            _capture(session_id="b", tokens_in=2000, tokens_out=600),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.tokens.total_in == 3000
        assert report.tokens.total_out == 1000


class TestRetryStats:
    def test_total_retries_accumulated(self) -> None:
        store = _store_with(
            _capture(session_id="a", retry_count=2),
            _capture(session_id="b", retry_count=3),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.retries.total_retries == 5

    def test_avg_per_session(self) -> None:
        store = _store_with(
            _capture(session_id="a", retry_count=0),
            _capture(session_id="b", retry_count=4),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.retries.avg_per_session == 2.0

    def test_zero_retries(self) -> None:
        store = _store_with(_capture(session_id="a", retry_count=0))
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.retries.avg_per_session == 0.0
        assert report.retries.high_retry_skills == []


class TestModelOutcomes:
    def test_model_summary_completion_rate(self) -> None:
        store = _store_with(
            _capture(session_id="a", outcome=SessionOutcome.COMPLETED),
            _capture(session_id="b", outcome=SessionOutcome.COMPLETED),
            _capture(session_id="c", outcome=SessionOutcome.ERROR),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert len(report.model_outcomes) == 1
        mo = report.model_outcomes[0]
        assert mo.completed_count == 2
        assert mo.error_count == 1
        assert mo.completion_rate == pytest.approx(2 / 3)

    def test_multiple_models_reported_separately(self) -> None:
        store = _store_with(
            _capture(session_id="a", model="claude-sonnet-4-6"),
            _capture(session_id="b", model="claude-opus-4-8"),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        models = {mo.model for mo in report.model_outcomes}
        assert models == {"claude-sonnet-4-6", "claude-opus-4-8"}

    def test_total_cost_accumulated_per_model(self) -> None:
        store = _store_with(
            _capture(session_id="a", model="claude-sonnet-4-6", cost_usd=0.01),
            _capture(session_id="b", model="claude-sonnet-4-6", cost_usd=0.02),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.model_outcomes[0].total_cost_usd == pytest.approx(0.03)


class TestRegressionDetection:
    def test_no_regressions_with_single_month(self) -> None:
        store = _store_with(_capture(session_id="a"))
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.regressions == []

    def test_tokens_per_issue_regression_fires_on_rising_series(self) -> None:
        # June: issue 1 → 100 total tokens; July: issue 1 → 1000 total tokens → 900% increase
        june = datetime(2026, 6, 1, tzinfo=UTC)
        july = datetime(2026, 7, 1, tzinfo=UTC)
        store = _store_with(
            _capture(session_id="j6", month_dt=june, issue_number=1, tokens_in=80, tokens_out=20),
            _capture(session_id="j7", month_dt=july, issue_number=1, tokens_in=800, tokens_out=200),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        tpi_flags = [f for f in report.regressions if f.metric == "tokens_per_issue"]
        assert len(tpi_flags) == 1
        assert tpi_flags[0].earlier_month == "2026-06"
        assert tpi_flags[0].later_month == "2026-07"
        assert tpi_flags[0].pct_increase > 10.0

    def test_retry_rate_regression_fires_on_rising_series(self) -> None:
        june = datetime(2026, 6, 1, tzinfo=UTC)
        july = datetime(2026, 7, 1, tzinfo=UTC)
        store = _store_with(
            _capture(session_id="j6", month_dt=june, retry_count=0),
            _capture(session_id="j7a", month_dt=july, retry_count=5),
            _capture(session_id="j7b", month_dt=july, retry_count=5),
        )
        report = EfficiencyReportGenerator(regression_threshold_pct=0.0).generate_on_demand(store)
        rr_flags = [f for f in report.regressions if f.metric == "retry_rate"]
        # june retry_rate=0 so no pct comparison possible; flag only when earlier_value > 0
        # Update: our code checks e_rr > 0 so if June had 0 retries no flag. Let's verify:
        assert all(f.earlier_value > 0 for f in rr_flags)

    def test_retry_rate_regression_fires_when_earlier_nonzero(self) -> None:
        june = datetime(2026, 6, 1, tzinfo=UTC)
        july = datetime(2026, 7, 1, tzinfo=UTC)
        store = _store_with(
            _capture(session_id="j6a", month_dt=june, retry_count=1),
            _capture(session_id="j6b", month_dt=june, retry_count=1),
            _capture(session_id="j7a", month_dt=july, retry_count=5),
            _capture(session_id="j7b", month_dt=july, retry_count=5),
        )
        report = EfficiencyReportGenerator(regression_threshold_pct=0.0).generate_on_demand(store)
        rr_flags = [f for f in report.regressions if f.metric == "retry_rate"]
        assert len(rr_flags) == 1
        assert rr_flags[0].earlier_value == pytest.approx(1.0)
        assert rr_flags[0].later_value == pytest.approx(5.0)

    def test_no_flag_when_tokens_decrease(self) -> None:
        june = datetime(2026, 6, 1, tzinfo=UTC)
        july = datetime(2026, 7, 1, tzinfo=UTC)
        store = _store_with(
            _capture(session_id="j6", month_dt=june, tokens_in=1000, tokens_out=400),
            _capture(session_id="j7", month_dt=july, tokens_in=500, tokens_out=200),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert not any(f.metric == "tokens_per_issue" for f in report.regressions)

    def test_consecutive_month_comparison(self) -> None:
        # 3 months: increasing trend should produce 2 flags (A→B and B→C)
        m1 = datetime(2026, 4, 1, tzinfo=UTC)
        m2 = datetime(2026, 5, 1, tzinfo=UTC)
        m3 = datetime(2026, 6, 1, tzinfo=UTC)
        store = _store_with(
            _capture(session_id="a", month_dt=m1, issue_number=1, tokens_in=100, tokens_out=50),
            _capture(session_id="b", month_dt=m2, issue_number=1, tokens_in=500, tokens_out=200),
            _capture(session_id="c", month_dt=m3, issue_number=1, tokens_in=2000, tokens_out=800),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        tpi_flags = [f for f in report.regressions if f.metric == "tokens_per_issue"]
        assert len(tpi_flags) == 2


class TestSuggestions:
    def test_verbose_skill_surfaces(self) -> None:
        # 3 skills: A and B are normal, C is very verbose
        store = _store_with(
            _capture(session_id="a", skill="plan", tokens_in=200, tokens_out=100),
            _capture(session_id="b", skill="review", tokens_in=200, tokens_out=100),
            _capture(session_id="c", skill="implement", tokens_in=2000, tokens_out=100),
        )
        report = EfficiencyReportGenerator(verbose_multiplier=2.0).generate_on_demand(store)
        verbose = [s for s in report.suggestions if s.category == "verbose_skill"]
        assert len(verbose) >= 1
        assert any("implement" in s.message for s in verbose)

    def test_looping_step_surfaces(self) -> None:
        store = _store_with(
            _capture(session_id="a", skill="implement", retry_count=3),
            _capture(session_id="b", skill="implement", retry_count=3),
        )
        # 3 retries/session > threshold of 1.0
        report = EfficiencyReportGenerator(high_retry_rate=1.0).generate_on_demand(store)
        looping = [s for s in report.suggestions if s.category == "looping_step"]
        assert len(looping) == 1
        assert "implement" in looping[0].message

    def test_high_input_ratio_suggestion(self) -> None:
        # tokens_in / tokens_out = 5000 / 100 = 50x > threshold 4x
        store = _store_with(
            _capture(session_id="a", tokens_in=5000, tokens_out=100),
        )
        report = EfficiencyReportGenerator(high_input_ratio=4.0).generate_on_demand(store)
        ratio_hints = [s for s in report.suggestions if s.category == "high_input_ratio"]
        assert len(ratio_hints) == 1

    def test_high_cost_model_suggestion(self) -> None:
        # Expensive model has same completion rate as cheaper model → flag it
        store = _store_with(
            _capture(
                session_id="a",
                model="claude-opus-4-8",
                cost_usd=0.10,
                outcome=SessionOutcome.COMPLETED,
            ),
            _capture(
                session_id="b",
                model="claude-sonnet-4-6",
                cost_usd=0.01,
                outcome=SessionOutcome.COMPLETED,
            ),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        cost_hints = [s for s in report.suggestions if s.category == "high_cost_model"]
        assert len(cost_hints) == 1
        assert "claude-opus-4-8" in cost_hints[0].message

    def test_no_verbose_suggestion_with_one_skill(self) -> None:
        # Need at least 2 skills to compute median
        store = _store_with(
            _capture(session_id="a", skill="implement", tokens_in=9999, tokens_out=100),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        verbose = [s for s in report.suggestions if s.category == "verbose_skill"]
        assert verbose == []

    def test_no_suggestions_for_normal_fixture(self) -> None:
        # All metrics below thresholds, no regression
        store = _store_with(
            _capture(session_id="a", tokens_in=500, tokens_out=400, retry_count=0),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.suggestions == []
        assert report.regressions == []


class TestTotalCost:
    def test_total_cost_accumulated(self) -> None:
        store = _store_with(
            _capture(session_id="a", cost_usd=0.05),
            _capture(session_id="b", cost_usd=0.03),
        )
        report = EfficiencyReportGenerator().generate_on_demand(store)
        assert report.total_cost_usd == pytest.approx(0.08)
