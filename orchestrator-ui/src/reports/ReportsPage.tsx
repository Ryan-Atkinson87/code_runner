import { useCallback, useEffect, useReducer, useState } from "react";
import { ApiError, apiClient } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § Efficiency reports)
// ---------------------------------------------------------------------------

type Scope = "all" | "wave" | "month";

interface Wave {
  name: string;
  milestone_number: number;
  state: "open" | "closed";
}

interface TokenBreakdown {
  by_issue: Record<string, number>;
  by_role: Record<string, number>;
  by_skill: Record<string, number>;
  by_wave: Record<string, number>;
  total_in: number;
  total_out: number;
}

interface RetrySummary {
  total_retries: number;
  avg_per_session: number;
  high_retry_skills: string[];
}

interface ModelOutcome {
  model: string;
  session_count: number;
  completed_count: number;
  blocked_count: number;
  error_count: number;
  total_tokens: number;
  total_cost_usd: number;
  completion_rate: number;
}

interface Regression {
  metric: string;
  earlier_month: string;
  later_month: string;
  earlier_value: number;
  later_value: number;
  pct_increase: number;
}

interface Suggestion {
  category: string;
  message: string;
}

export interface EfficiencyReport {
  scope: string;
  generated_at: string;
  total_sessions: number;
  total_cost_usd: number;
  tokens: TokenBreakdown;
  retries: RetrySummary;
  model_outcomes: ModelOutcome[];
  regressions: Regression[];
  suggestions: Suggestion[];
}

// ---------------------------------------------------------------------------
// Report state reducer
// ---------------------------------------------------------------------------

type ReportState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "populated"; report: EfficiencyReport };

type ReportAction =
  | { type: "fetch_start" }
  | { type: "fetched"; report: EfficiencyReport }
  | { type: "fetch_error"; message: string }
  | { type: "reset" };

function reportReducer(_state: ReportState, action: ReportAction): ReportState {
  switch (action.type) {
    case "fetch_start":
      return { phase: "loading" };
    case "fetched":
      return action.report.total_sessions === 0
        ? { phase: "empty" }
        : { phase: "populated", report: action.report };
    case "fetch_error":
      return { phase: "error", message: action.message };
    case "reset":
      return { phase: "idle" };
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function reportUrl(scope: Scope, wave: string, month: string): string | null {
  if (scope === "all") return "/reports";
  if (scope === "wave") {
    if (!wave) return null;
    return `/reports/wave/${encodeURIComponent(wave)}`;
  }
  if (!/^\d{4}-\d{2}$/.test(month)) return null;
  return `/reports/month/${month}`;
}

function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

// ---------------------------------------------------------------------------
// Report sub-components
// ---------------------------------------------------------------------------

function SummaryCards({ report }: { report: EfficiencyReport }) {
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Sessions</p>
        <p className="mt-1 text-2xl font-semibold text-gray-900">
          {report.total_sessions}
        </p>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Total cost</p>
        <p className="mt-1 text-2xl font-semibold text-gray-900">
          {formatCost(report.total_cost_usd)}
        </p>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Total tokens</p>
        <p className="mt-1 text-2xl font-semibold text-gray-900">
          {formatNumber(report.tokens.total_in + report.tokens.total_out)}
        </p>
        <p className="mt-0.5 text-xs text-gray-500">
          {formatNumber(report.tokens.total_in)} in /{" "}
          {formatNumber(report.tokens.total_out)} out
        </p>
      </div>
    </div>
  );
}

function BreakdownTable({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;
  const headingId = `bd-${slug(title)}`;
  return (
    <section
      aria-labelledby={headingId}
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
    >
      <h2
        id={headingId}
        className="border-b border-gray-100 px-4 py-2 text-sm font-semibold text-gray-900"
      >
        {title}
      </h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-xs text-gray-500">
            <th scope="col" className="px-4 py-2 text-left font-medium">
              Name
            </th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              Tokens
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, val]) => (
            <tr key={key} className="border-b border-gray-50 last:border-0">
              <td className="px-4 py-2 text-gray-800">{key}</td>
              <td className="px-4 py-2 text-right text-gray-700">
                {formatNumber(val)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RetriesSection({ retries }: { retries: RetrySummary }) {
  return (
    <section
      aria-labelledby="retries-heading"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <h2
        id="retries-heading"
        className="mb-2 text-sm font-semibold text-gray-900"
      >
        Retry Clustering
      </h2>
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-gray-500">Total retries</dt>
          <dd className="text-sm font-medium text-gray-900">
            {retries.total_retries}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Avg per session</dt>
          <dd className="text-sm font-medium text-gray-900">
            {retries.avg_per_session.toFixed(2)}
          </dd>
        </div>
      </dl>
      {retries.high_retry_skills.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-gray-500">High-retry skills:</p>
          <ul className="mt-1 flex flex-wrap gap-1">
            {retries.high_retry_skills.map((s) => (
              <li
                key={s}
                className="rounded bg-orange-100 px-2 py-0.5 text-xs text-orange-800"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ModelOutcomesTable({ outcomes }: { outcomes: ModelOutcome[] }) {
  if (outcomes.length === 0) return null;
  return (
    <section
      aria-labelledby="model-outcomes-heading"
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
    >
      <h2
        id="model-outcomes-heading"
        className="border-b border-gray-100 px-4 py-2 text-sm font-semibold text-gray-900"
      >
        Model vs. Outcome
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-xs text-gray-500">
              <th scope="col" className="px-4 py-2 text-left font-medium">
                Model
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Sessions
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Completion
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Tokens
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((o) => (
              <tr key={o.model} className="border-b border-gray-50 last:border-0">
                <td className="px-4 py-2 font-mono text-xs text-gray-800">
                  {o.model}
                </td>
                <td className="px-4 py-2 text-right text-gray-700">
                  {o.session_count}
                </td>
                <td className="px-4 py-2 text-right">
                  <span
                    className={
                      o.completion_rate < 0.8
                        ? "font-medium text-orange-600"
                        : "text-gray-700"
                    }
                  >
                    {Math.round(o.completion_rate * 100)}%
                  </span>
                  <span
                    aria-label={`${o.completed_count} completed, ${o.blocked_count} blocked, ${o.error_count} errored`}
                    className="ml-1 text-xs text-gray-400"
                  >
                    <span aria-hidden="true">({o.completed_count}✓ {o.blocked_count}⚠ {o.error_count}✕)</span>
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-gray-700">
                  {formatNumber(o.total_tokens)}
                </td>
                <td className="px-4 py-2 text-right text-gray-700">
                  {formatCost(o.total_cost_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RegressionFlags({ regressions }: { regressions: Regression[] }) {
  if (regressions.length === 0) return null;
  return (
    <section aria-labelledby="regressions-heading">
      <h2
        id="regressions-heading"
        className="mb-2 text-sm font-semibold text-gray-900"
      >
        Month-over-Month Regressions
      </h2>
      <ul className="space-y-2">
        {regressions.map((r, idx) => (
          <li
            key={idx}
            className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 p-3 text-sm"
          >
            <span aria-hidden="true" className="flex-shrink-0 text-orange-500">
              ⚠
            </span>
            <div>
              <p className="font-medium text-orange-900">
                {r.metric.replace(/_/g, " ")}
              </p>
              <p className="text-xs text-orange-700">
                {r.earlier_month}: {r.earlier_value.toFixed(1)} →{" "}
                {r.later_month}: {r.later_value.toFixed(1)} (+
                {r.pct_increase.toFixed(1)}%)
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SuggestionsList({ suggestions }: { suggestions: Suggestion[] }) {
  if (suggestions.length === 0) return null;
  return (
    <section aria-labelledby="suggestions-heading">
      <h2
        id="suggestions-heading"
        className="mb-2 text-sm font-semibold text-gray-900"
      >
        Suggestions
      </h2>
      <ul className="space-y-2">
        {suggestions.map((s, idx) => (
          <li
            key={idx}
            className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm"
          >
            <p className="mb-0.5 text-xs font-medium uppercase text-blue-600">
              {s.category.replace(/_/g, " ")}
            </p>
            <p className="text-blue-900">{s.message}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReportView({ report }: { report: EfficiencyReport }) {
  const generatedAt = new Date(report.generated_at).toLocaleString();
  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        Generated {generatedAt} · scope: {report.scope}
      </p>
      <SummaryCards report={report} />
      <div className="grid gap-4 md:grid-cols-2">
        <BreakdownTable
          title="Tokens by Role"
          data={report.tokens.by_role}
        />
        <BreakdownTable
          title="Tokens by Skill"
          data={report.tokens.by_skill}
        />
      </div>
      <BreakdownTable title="Tokens by Wave" data={report.tokens.by_wave} />
      <RetriesSection retries={report.retries} />
      <ModelOutcomesTable outcomes={report.model_outcomes} />
      <RegressionFlags regressions={report.regressions} />
      <SuggestionsList suggestions={report.suggestions} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const SCOPE_TABS: { id: Scope; label: string }[] = [
  { id: "all", label: "All Data" },
  { id: "wave", label: "By Wave" },
  { id: "month", label: "By Month" },
];

export function ReportsPage() {
  const [scope, setScope] = useState<Scope>("all");
  const [selectedWave, setSelectedWave] = useState("");
  const [selectedMonth, setSelectedMonth] = useState("");
  const [waves, setWaves] = useState<Wave[]>([]);
  const [wavesLoading, setWavesLoading] = useState(true);
  const [reportState, dispatch] = useReducer(reportReducer, { phase: "idle" });

  // Load waves on mount for the "By Wave" selector.
  useEffect(() => {
    const controller = new AbortController();
    apiClient
      .get<{ waves: Wave[] }>("/runs/waves", controller.signal)
      .then((data) => setWaves(data.waves))
      .catch(() => {})
      .finally(() => setWavesLoading(false));
    return () => {
      controller.abort();
    };
  }, []);

  const fetchReport = useCallback(async (url: string, signal?: AbortSignal) => {
    dispatch({ type: "fetch_start" });
    try {
      const report = await apiClient.get<EfficiencyReport>(url, signal);
      dispatch({ type: "fetched", report });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({
        type: "fetch_error",
        message:
          err instanceof ApiError ? err.message : "Failed to load report",
      });
    }
  }, []);

  // Fetch report whenever scope or selection changes.
  useEffect(() => {
    const url = reportUrl(scope, selectedWave, selectedMonth);
    if (!url) {
      dispatch({ type: "reset" });
      return;
    }
    const controller = new AbortController();
    void fetchReport(url, controller.signal);
    return () => {
      controller.abort();
    };
  }, [scope, selectedWave, selectedMonth, fetchReport]);

  function handleScopeChange(newScope: Scope) {
    setScope(newScope);
    if (newScope !== "wave") setSelectedWave("");
    if (newScope !== "month") setSelectedMonth("");
  }

  const emptyAction =
    scope !== "all" ? (
      <button
        type="button"
        onClick={() => handleScopeChange("all")}
        className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        View all data
      </button>
    ) : (
      <button
        type="button"
        onClick={() => void fetchReport("/reports")}
        className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        Refresh
      </button>
    );

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold text-gray-900">
        Efficiency Reports
      </h1>

      {/* Scope tabs */}
      <div
        role="tablist"
        aria-label="Report scope"
        className="mb-6 flex w-fit gap-1 rounded-lg bg-gray-100 p-1"
      >
        {SCOPE_TABS.map((tab) => (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            role="tab"
            aria-selected={scope === tab.id}
            aria-controls="report-panel"
            type="button"
            onClick={() => handleScopeChange(tab.id)}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              scope === tab.id
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Wave selector */}
      {scope === "wave" && (
        <div className="mb-6">
          {wavesLoading ? (
            <p className="text-sm text-gray-500">Loading waves…</p>
          ) : waves.length === 0 ? (
            <p className="text-sm text-gray-500">No waves available.</p>
          ) : (
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-gray-700">
                Select wave
              </span>
              <select
                value={selectedWave}
                onChange={(e) => setSelectedWave(e.target.value)}
                className="rounded border border-gray-300 px-3 py-2 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">— choose a wave —</option>
                {waves.map((w) => (
                  <option key={w.name} value={w.name}>
                    {w.name} ({w.state})
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      {/* Month selector */}
      {scope === "month" && (
        <div className="mb-6">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">
              Select month
            </span>
            <input
              type="month"
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="rounded border border-gray-300 px-3 py-2 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>
        </div>
      )}

      {/* Report panel */}
      <div id="report-panel" role="tabpanel" aria-labelledby={`tab-${scope}`}>
        {reportState.phase === "idle" && (
          <p className="text-sm text-gray-500">
            {scope === "wave"
              ? "Select a wave above to load its report."
              : "Select a month above to load its report."}
          </p>
        )}
        {reportState.phase === "loading" && <LoadingState />}
        {reportState.phase === "empty" && (
          <EmptyState
            message="No data available for this scope — efficiency data accumulates as sessions complete."
            action={emptyAction}
          />
        )}
        {reportState.phase === "error" && (
          <ErrorState
            message={reportState.message}
            retry={() => {
              const url = reportUrl(scope, selectedWave, selectedMonth);
              if (url) void fetchReport(url);
            }}
          />
        )}
        {reportState.phase === "populated" && (
          <ReportView report={reportState.report} />
        )}
      </div>
    </div>
  );
}
