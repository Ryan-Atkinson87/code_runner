import { useCallback, useEffect, useReducer } from "react";
import { ApiError, apiClient } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PopulatedState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § GET /usage/gauges)
// ---------------------------------------------------------------------------

interface Meter {
  kind: string;
  utilisation: number;
  resets_at: number | null;
  limit: number | null;
  used: number | null;
  is_governing: boolean;
}

interface GaugesSnapshot {
  meters: Meter[];
  threshold_percent: number;
  threshold_reached: boolean;
  override_active: boolean;
  provider: string;
  plan: string;
}

interface OverrideResponse {
  override_active: boolean;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type PageState =
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "populated"; data: GaugesSnapshot; overriding: boolean; overrideError: string | null };

type PageAction =
  | { type: "loaded"; data: GaugesSnapshot }
  | { type: "load_error"; message: string }
  | { type: "override_start" }
  | { type: "override_done"; override_active: boolean }
  | { type: "override_error"; message: string };

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "loaded":
      if (action.data.meters.length === 0) return { phase: "empty" };
      return { phase: "populated", data: action.data, overriding: false, overrideError: null };
    case "load_error":
      return { phase: "error", message: action.message };
    case "override_start":
      if (state.phase !== "populated") return state;
      return { ...state, overriding: true, overrideError: null };
    case "override_done":
      if (state.phase !== "populated") return state;
      return {
        ...state,
        overriding: false,
        data: { ...state.data, override_active: action.override_active },
        overrideError: null,
      };
    case "override_error":
      if (state.phase !== "populated") return state;
      return { ...state, overriding: false, overrideError: action.message };
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatKind(kind: string): string {
  return kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function formatResetTime(ts: number): string {
  return new Date(ts * 1000).toUTCString().replace(/ GMT$/, " UTC");
}

// ---------------------------------------------------------------------------
// Gauge sub-component
// ---------------------------------------------------------------------------

interface GaugeProps {
  meter: Meter;
  thresholdPercent: number;
}

function MeterGauge({ meter, thresholdPercent }: GaugeProps) {
  const pct = Math.min(meter.utilisation * 100, 100);
  const breached = meter.utilisation * 100 >= thresholdPercent;
  const fillClass = meter.is_governing
    ? breached
      ? "bg-red-500"
      : "bg-indigo-500"
    : breached
      ? "bg-orange-400"
      : "bg-gray-400";

  return (
    <article
      aria-label={`${formatKind(meter.kind)} meter${meter.is_governing ? " (governing)" : ""}`}
      className={`rounded-lg border p-4 shadow-sm ${
        meter.is_governing
          ? "border-indigo-400 bg-indigo-50"
          : "border-gray-200 bg-white"
      }`}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">
          {formatKind(meter.kind)}
        </h2>
        {meter.is_governing && (
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800">
            Governing
          </span>
        )}
      </div>

      {/* Bar */}
      <div className="relative mb-1">
        <div
          role="meter"
          aria-label={`${formatKind(meter.kind)} usage`}
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuetext={`${Math.round(pct)}% used${breached ? ", threshold reached" : ""}`}
          className="h-4 overflow-hidden rounded-full bg-gray-200"
        >
          <div
            className={`h-full rounded-full transition-all ${fillClass}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        {/* Threshold marker */}
        <div
          aria-hidden="true"
          className="absolute top-0 h-4 w-0.5 bg-gray-700"
          style={{ left: `${thresholdPercent}%` }}
          title={`${thresholdPercent}% threshold`}
        />
      </div>

      {/* Labels */}
      <div className="flex justify-between text-xs text-gray-500">
        <span>0%</span>
        <span
          className={
            breached ? "font-semibold text-red-600" : "text-gray-500"
          }
        >
          {thresholdPercent}% threshold{breached ? " ⚠ reached" : ""}
        </span>
        <span className="font-medium text-gray-700">{Math.round(pct)}%</span>
      </div>

      {/* Detail */}
      {meter.used !== null && meter.limit !== null && (
        <p className="mt-2 text-xs text-gray-600">
          {formatNumber(meter.used)} / {formatNumber(meter.limit)} used
        </p>
      )}
      {meter.resets_at !== null && (
        <p className="mt-0.5 text-xs text-gray-500">
          Resets {formatResetTime(meter.resets_at)}
        </p>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 30_000;

export function UsageGaugesPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });

  const fetchGauges = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await apiClient.get<GaugesSnapshot>("/usage/gauges", signal);
      dispatch({ type: "loaded", data });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({
        type: "load_error",
        message: err instanceof ApiError ? err.message : "Failed to load usage data",
      });
    }
  }, []);

  // Initial fetch + polling
  useEffect(() => {
    const controller = new AbortController();
    void fetchGauges(controller.signal);
    const id = setInterval(() => {
      void fetchGauges(controller.signal);
    }, POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [fetchGauges]);

  async function handleOverrideToggle(currentlyActive: boolean) {
    const next = !currentlyActive;
    const verb = next ? "enable" : "disable";
    if (!window.confirm(`${verb === "enable" ? "Enable" : "Disable"} the usage override? This ${next ? "bypasses the 80% threshold gate" : "re-enables the threshold gate"}.`)) {
      return;
    }
    dispatch({ type: "override_start" });
    try {
      const res = await apiClient.post<OverrideResponse>("/usage/override", { active: next });
      dispatch({ type: "override_done", override_active: res.override_active });
    } catch (err) {
      dispatch({
        type: "override_error",
        message: err instanceof ApiError ? err.message : "Failed to toggle override — please try again.",
      });
    }
  }

  if (state.phase === "loading") return <LoadingState />;

  if (state.phase === "empty") {
    return (
      <EmptyState message="No usage meters available for the current provider." />
    );
  }

  if (state.phase === "error") {
    return (
      <ErrorState
        message={state.message}
        retry={() => { void fetchGauges(); }}
      />
    );
  }

  const { data, overriding, overrideError } = state;

  return (
    <PopulatedState className="p-6">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Usage Gauges</h1>
          <p className="mt-0.5 text-xs text-gray-500 capitalize">
            {data.provider} · {data.plan} plan
          </p>
        </div>
        {data.threshold_reached && (
          <span
            role="alert"
            className="rounded-full bg-red-100 px-3 py-1 text-sm font-medium text-red-700"
          >
            Threshold reached
          </span>
        )}
      </div>

      {/* Gauges */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.meters.map((m) => (
          <MeterGauge
            key={m.kind}
            meter={m}
            thresholdPercent={data.threshold_percent}
          />
        ))}
      </div>

      {/* Override control */}
      <section
        aria-labelledby="override-heading"
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      >
        <h2
          id="override-heading"
          className="mb-1 text-sm font-semibold text-gray-900"
        >
          Usage Override
        </h2>
        <p className="mb-3 text-xs text-gray-500">
          Enabling the override bypasses the {data.threshold_percent}% threshold gate and
          lets runs continue past the limit. Disable to re-engage the gate.
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={data.override_active}
            aria-label="Usage override"
            disabled={overriding}
            onClick={() => void handleOverrideToggle(data.override_active)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50 ${
              data.override_active ? "bg-indigo-600" : "bg-gray-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                data.override_active ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
          <span className="text-sm text-gray-700">
            {data.override_active ? "Override active — threshold gate bypassed" : "Override inactive — threshold gate active"}
          </span>
        </div>
        {overrideError && (
          <p role="alert" className="mt-2 text-xs text-red-600">
            {overrideError}
          </p>
        )}
      </section>
    </PopulatedState>
  );
}
