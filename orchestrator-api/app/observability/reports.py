from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from app.observability.rollup import RollupRow, RollupStore

# Thresholds — all overridable via EfficiencyReportGenerator constructor.
_REGRESSION_THRESHOLD_PCT: float = 10.0  # % month-over-month increase triggers a flag
_HIGH_RETRY_RATE: float = 1.0  # avg retries/session; above this → looping flag
_VERBOSE_SKILL_MULTIPLIER: float = 2.0  # skill avg tokens_in > n× median → verbose flag
_HIGH_INPUT_RATIO: float = 4.0  # total tokens_in / tokens_out; above → unused-context hint


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------


@dataclass
class TokenBreakdown:
    """Token totals (input + output) sliced by each rollup dimension."""

    by_issue: dict[int, int]  # issue_number → tokens
    by_role: dict[str, int]
    by_skill: dict[str, int]
    by_wave: dict[str, int]
    total_in: int
    total_out: int


@dataclass
class RetryStats:
    total_retries: int
    avg_per_session: float
    high_retry_skills: list[str]  # skills whose avg retry rate exceeds the threshold


@dataclass
class ModelOutcomeSummary:
    model: str
    session_count: int
    completed_count: int
    blocked_count: int
    error_count: int
    total_tokens: int
    total_cost_usd: float
    completion_rate: float


@dataclass
class RegressionFlag:
    """Month-over-month regression in a single metric."""

    metric: str  # "tokens_per_issue" | "retry_rate"
    earlier_month: str
    later_month: str
    earlier_value: float
    later_value: float
    pct_increase: float


@dataclass
class Suggestion:
    """Concrete efficiency suggestion derived from rollup data."""

    category: str  # "verbose_skill" | "looping_step" | "high_input_ratio" | "high_cost_model"
    message: str


@dataclass
class EfficiencyReport:
    scope: str  # "all" | "wave:<name>" | "month:<YYYY-MM>"
    generated_at: datetime
    total_sessions: int
    total_cost_usd: float
    tokens: TokenBreakdown
    retries: RetryStats
    model_outcomes: list[ModelOutcomeSummary]
    regressions: list[RegressionFlag]
    suggestions: list[Suggestion]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class EfficiencyReportGenerator:
    """Computes efficiency reports from Layer 2 rollup data (Spec §11.3).

    All computation is deterministic and reads only from RollupStore; Layer 1
    raw captures are not opened here — that is reserved for drilling into
    specific flagged sessions.
    """

    def __init__(
        self,
        regression_threshold_pct: float = _REGRESSION_THRESHOLD_PCT,
        high_retry_rate: float = _HIGH_RETRY_RATE,
        verbose_multiplier: float = _VERBOSE_SKILL_MULTIPLIER,
        high_input_ratio: float = _HIGH_INPUT_RATIO,
    ) -> None:
        self._regression_threshold_pct = regression_threshold_pct
        self._high_retry_rate = high_retry_rate
        self._verbose_multiplier = verbose_multiplier
        self._high_input_ratio = high_input_ratio

    def generate_on_demand(self, store: RollupStore) -> EfficiencyReport:
        rows = store.query()
        return self._build_report(rows, "all")

    def generate_for_wave(self, store: RollupStore, wave: str) -> EfficiencyReport:
        rows = store.query(wave=wave)
        return self._build_report(rows, f"wave:{wave}")

    def generate_for_month(self, store: RollupStore, month: str) -> EfficiencyReport:
        rows = store.query(month=month)
        return self._build_report(rows, f"month:{month}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_report(self, rows: list[RollupRow], scope: str) -> EfficiencyReport:
        model_outcomes = self._model_outcomes(rows)
        suggestions = self._suggestions(rows, model_outcomes)
        return EfficiencyReport(
            scope=scope,
            generated_at=datetime.now(UTC),
            total_sessions=sum(r.session_count for r in rows),
            total_cost_usd=sum(r.cost_usd for r in rows),
            tokens=self._token_breakdown(rows),
            retries=self._retry_stats(rows),
            model_outcomes=model_outcomes,
            regressions=self._detect_regressions(rows),
            suggestions=suggestions,
        )

    def _token_breakdown(self, rows: list[RollupRow]) -> TokenBreakdown:
        by_issue: dict[int, int] = {}
        by_role: dict[str, int] = {}
        by_skill: dict[str, int] = {}
        by_wave: dict[str, int] = {}

        for r in rows:
            tokens = r.tokens_in + r.tokens_out
            by_issue[r.issue_number] = by_issue.get(r.issue_number, 0) + tokens
            by_role[r.role] = by_role.get(r.role, 0) + tokens
            by_skill[r.skill] = by_skill.get(r.skill, 0) + tokens
            by_wave[r.wave] = by_wave.get(r.wave, 0) + tokens

        return TokenBreakdown(
            by_issue=by_issue,
            by_role=by_role,
            by_skill=by_skill,
            by_wave=by_wave,
            total_in=sum(r.tokens_in for r in rows),
            total_out=sum(r.tokens_out for r in rows),
        )

    def _retry_stats(self, rows: list[RollupRow]) -> RetryStats:
        total_retries = sum(r.retry_count for r in rows)
        total_sessions = sum(r.session_count for r in rows)
        avg = total_retries / total_sessions if total_sessions else 0.0

        # Per-skill retry rates
        skill_retries: dict[str, int] = {}
        skill_sessions: dict[str, int] = {}
        for r in rows:
            skill_retries[r.skill] = skill_retries.get(r.skill, 0) + r.retry_count
            skill_sessions[r.skill] = skill_sessions.get(r.skill, 0) + r.session_count

        high_retry_skills = [
            skill
            for skill, retries in skill_retries.items()
            if skill_sessions.get(skill, 0) > 0
            and retries / skill_sessions[skill] > self._high_retry_rate
        ]

        return RetryStats(
            total_retries=total_retries,
            avg_per_session=avg,
            high_retry_skills=sorted(high_retry_skills),
        )

    def _model_outcomes(self, rows: list[RollupRow]) -> list[ModelOutcomeSummary]:
        model_data: dict[str, list[RollupRow]] = {}
        for r in rows:
            model_data.setdefault(r.model, []).append(r)

        summaries: list[ModelOutcomeSummary] = []
        for model, model_rows in sorted(model_data.items()):
            sessions = sum(r.session_count for r in model_rows)
            completed = sum(r.completed_count for r in model_rows)
            blocked = sum(r.blocked_count for r in model_rows)
            error = sum(r.error_count for r in model_rows)
            tokens = sum(r.tokens_in + r.tokens_out for r in model_rows)
            cost = sum(r.cost_usd for r in model_rows)
            rate = completed / sessions if sessions else 0.0
            summaries.append(
                ModelOutcomeSummary(
                    model=model,
                    session_count=sessions,
                    completed_count=completed,
                    blocked_count=blocked,
                    error_count=error,
                    total_tokens=tokens,
                    total_cost_usd=cost,
                    completion_rate=rate,
                )
            )
        return summaries

    def _detect_regressions(self, rows: list[RollupRow]) -> list[RegressionFlag]:
        months_data: dict[str, list[RollupRow]] = {}
        for r in rows:
            months_data.setdefault(r.month, []).append(r)

        sorted_months = sorted(months_data.keys())
        if len(sorted_months) < 2:
            return []

        flags: list[RegressionFlag] = []
        for i in range(len(sorted_months) - 1):
            earlier = sorted_months[i]
            later = sorted_months[i + 1]
            e_rows = months_data[earlier]
            l_rows = months_data[later]

            e_tpi = _tokens_per_issue(e_rows)
            l_tpi = _tokens_per_issue(l_rows)
            if e_tpi > 0:
                pct = (l_tpi - e_tpi) / e_tpi * 100
                if pct > self._regression_threshold_pct:
                    flags.append(
                        RegressionFlag(
                            metric="tokens_per_issue",
                            earlier_month=earlier,
                            later_month=later,
                            earlier_value=e_tpi,
                            later_value=l_tpi,
                            pct_increase=pct,
                        )
                    )

            e_rr = _retry_rate(e_rows)
            l_rr = _retry_rate(l_rows)
            if e_rr > 0:
                pct = (l_rr - e_rr) / e_rr * 100
                if pct > self._regression_threshold_pct:
                    flags.append(
                        RegressionFlag(
                            metric="retry_rate",
                            earlier_month=earlier,
                            later_month=later,
                            earlier_value=e_rr,
                            later_value=l_rr,
                            pct_increase=pct,
                        )
                    )

        return flags

    def _suggestions(
        self, rows: list[RollupRow], model_outcomes: list[ModelOutcomeSummary]
    ) -> list[Suggestion]:
        suggestions: list[Suggestion] = []

        # --- Verbose skill ---
        skill_in: dict[str, int] = {}
        skill_sessions: dict[str, int] = {}
        skill_retries: dict[str, int] = {}
        for r in rows:
            skill_in[r.skill] = skill_in.get(r.skill, 0) + r.tokens_in
            skill_sessions[r.skill] = skill_sessions.get(r.skill, 0) + r.session_count
            skill_retries[r.skill] = skill_retries.get(r.skill, 0) + r.retry_count

        avg_in_per_session: dict[str, float] = {
            s: skill_in[s] / skill_sessions[s] for s in skill_in if skill_sessions.get(s, 0) > 0
        }

        if len(avg_in_per_session) >= 2:
            med = median(avg_in_per_session.values())
            threshold = med * self._verbose_multiplier
            for skill, avg in avg_in_per_session.items():
                if avg > threshold:
                    suggestions.append(
                        Suggestion(
                            category="verbose_skill",
                            message=(
                                f"Skill '{skill}' averages {avg:.0f} input tokens/session "
                                f"({avg / med:.1f}× median) — the prompt may be loading "
                                f"more context than needed."
                            ),
                        )
                    )

        # --- Looping step ---
        for skill, retries in skill_retries.items():
            sessions = skill_sessions.get(skill, 0)
            if sessions > 0 and retries / sessions > self._high_retry_rate:
                suggestions.append(
                    Suggestion(
                        category="looping_step",
                        message=(
                            f"Skill '{skill}' averages {retries / sessions:.1f} retries/session "
                            f"— the implementation loop may be cycling on a recurring pattern."
                        ),
                    )
                )

        # --- High input/output ratio (possible unused context) ---
        total_in = sum(r.tokens_in for r in rows)
        total_out = sum(r.tokens_out for r in rows)
        if total_out > 0 and total_in / total_out > self._high_input_ratio:
            suggestions.append(
                Suggestion(
                    category="high_input_ratio",
                    message=(
                        f"Overall input/output ratio is {total_in / total_out:.1f}× — large "
                        f"context relative to output may indicate context loaded but unused "
                        f"(drill into flagged sessions via Layer 1 for details)."
                    ),
                )
            )

        # --- High-cost model without quality benefit ---
        suggestions.extend(self._model_cost_suggestions(model_outcomes))

        return suggestions

    def _model_cost_suggestions(
        self, model_outcomes: list[ModelOutcomeSummary]
    ) -> list[Suggestion]:
        if len(model_outcomes) < 2:
            return []

        suggestions: list[Suggestion] = []
        for i, m1 in enumerate(model_outcomes):
            if m1.session_count == 0:
                continue
            cost1 = m1.total_cost_usd / m1.session_count
            for m2 in model_outcomes[i + 1 :]:
                if m2.session_count == 0:
                    continue
                cost2 = m2.total_cost_usd / m2.session_count
                if cost1 > cost2 and m1.completion_rate <= m2.completion_rate:
                    suggestions.append(
                        Suggestion(
                            category="high_cost_model",
                            message=(
                                f"Model '{m1.model}' costs ${cost1:.4f}/session with "
                                f"{m1.completion_rate:.0%} completion; '{m2.model}' costs "
                                f"${cost2:.4f}/session with {m2.completion_rate:.0%} — "
                                f"the cheaper model may suffice."
                            ),
                        )
                    )
        return suggestions


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _tokens_per_issue(rows: list[RollupRow]) -> float:
    issues = {r.issue_number for r in rows}
    if not issues:
        return 0.0
    total = sum(r.tokens_in + r.tokens_out for r in rows)
    return total / len(issues)


def _retry_rate(rows: list[RollupRow]) -> float:
    sessions = sum(r.session_count for r in rows)
    if not sessions:
        return 0.0
    retries = sum(r.retry_count for r in rows)
    return retries / sessions
