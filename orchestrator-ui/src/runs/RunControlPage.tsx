import { useCallback, useEffect, useReducer, useState } from "react";
import { ApiError, apiClient } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PopulatedState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (mirroring docs/api.md Run control section)
// ---------------------------------------------------------------------------

interface ConfigMeta {
  github_url?: string;
}

type RunStatus =
  | "pending"
  | "running"
  | "paused"
  | "stopped"
  | "completed"
  | "failed";

interface Wave {
  name: string;
  milestone_number: number;
  state: "open" | "closed";
}

interface RunState {
  run_id: number;
  project: string;
  wave: string;
  provider: string;
  status: RunStatus;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type PageState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | {
      phase: "ready";
      waves: Wave[];
      providers: string[];
      run: RunState | null;
      actionError: string | null;
      acting: boolean;
    };

type PageAction =
  | { type: "reset" }
  | { type: "loaded"; waves: Wave[]; providers: string[]; run: RunState | null }
  | { type: "load_error"; message: string }
  | { type: "action_start" }
  | { type: "action_done"; run: RunState | null }
  | { type: "action_error"; message: string }
  | { type: "dismiss_error" };

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "reset":
      return { phase: "loading" };
    case "loaded":
      return {
        phase: "ready",
        waves: action.waves,
        providers: action.providers,
        run: action.run,
        actionError: null,
        acting: false,
      };
    case "load_error":
      return { phase: "error", message: action.message };
    case "action_start":
      if (state.phase !== "ready") return state;
      return { ...state, acting: true, actionError: null };
    case "action_done":
      if (state.phase !== "ready") return state;
      return { ...state, acting: false, run: action.run };
    case "action_error":
      if (state.phase !== "ready") return state;
      return { ...state, acting: false, actionError: action.message };
    case "dismiss_error":
      if (state.phase !== "ready") return state;
      return { ...state, actionError: null };
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<RunStatus, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-green-100 text-green-800",
  paused: "bg-blue-100 text-blue-800",
  stopped: "bg-gray-100 text-gray-600",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-700",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[status]}`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function isActionableStatus(status: RunStatus): boolean {
  return status === "running" || status === "paused" || status === "pending";
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RunControlPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });
  const [githubMilestonesUrl, setGithubMilestonesUrl] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    dispatch({ type: "reset" });
    try {
      const [wavesRes, statusRes, providersRes] = await Promise.all([
        apiClient.get<{ waves: Wave[] }>("/runs/waves", signal),
        apiClient.get<{ active: boolean; run: RunState | null }>(
          "/runs/status",
          signal,
        ),
        apiClient.get<{ providers: string[] }>("/config/providers", signal),
      ]);
      if (signal?.aborted) return;
      dispatch({
        type: "loaded",
        waves: wavesRes.waves,
        providers: providersRes.providers,
        run: statusRes.run,
      });
    } catch (err) {
      if (signal?.aborted) return;
      dispatch({
        type: "load_error",
        message: extractMessage(err, "Failed to load run data"),
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    apiClient
      .get<ConfigMeta>("/config", controller.signal)
      .then((cfg) => {
        if (cfg?.github_url) {
          setGithubMilestonesUrl(`${cfg.github_url}/milestones`);
        }
      })
      .catch(() => {});
    return () => { controller.abort(); };
  }, []);

  if (state.phase === "loading") return <LoadingState />;
  if (state.phase === "error")
    return <ErrorState message={state.message} retry={() => void load()} />;

  const { waves, providers, run, actionError, acting } = state;
  const isActive = run !== null && isActionableStatus(run.status);
  const openWaves = waves.filter((w) => w.state === "open");

  async function handleStart(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    dispatch({ type: "action_start" });
    try {
      const res = await apiClient.post<RunState>("/runs/start", {
        wave: fd.get("wave") as string,
        provider: fd.get("provider") as string,
      });
      dispatch({ type: "action_done", run: res });
    } catch (err) {
      dispatch({
        type: "action_error",
        message: extractMessage(err, "Failed to start run"),
      });
    }
  }

  async function handleStop(runId: number) {
    if (!window.confirm("Stop this run? The agent will be interrupted immediately."))
      return;
    dispatch({ type: "action_start" });
    try {
      const res = await apiClient.post<RunState>(`/runs/${runId}/stop`);
      dispatch({ type: "action_done", run: res });
    } catch (err) {
      dispatch({
        type: "action_error",
        message: extractMessage(err, "Failed to stop run"),
      });
    }
  }

  async function handlePause(runId: number) {
    if (
      !window.confirm(
        "Pause this run? The agent will finish its current step before pausing.",
      )
    )
      return;
    dispatch({ type: "action_start" });
    try {
      const res = await apiClient.post<RunState>(`/runs/${runId}/pause`);
      dispatch({ type: "action_done", run: res });
    } catch (err) {
      dispatch({
        type: "action_error",
        message: extractMessage(err, "Failed to pause run"),
      });
    }
  }

  async function handleResume(runId: number) {
    dispatch({ type: "action_start" });
    try {
      const res = await apiClient.post<RunState>(`/runs/${runId}/resume`);
      dispatch({ type: "action_done", run: res });
    } catch (err) {
      dispatch({
        type: "action_error",
        message: extractMessage(err, "Failed to resume run"),
      });
    }
  }

  return (
    <PopulatedState className="max-w-2xl p-6">
      <h1 className="mb-6 text-xl font-semibold text-gray-900">Run Control</h1>

      {actionError && (
        <div
          role="alert"
          className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {actionError}
          <button
            type="button"
            onClick={() => dispatch({ type: "dismiss_error" })}
            aria-label="Dismiss error"
            className="ml-3 underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Current / most-recent run info */}
      {run !== null && (
        <section
          aria-labelledby="run-panel-heading"
          className="mb-8 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        >
          <h2
            id="run-panel-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500"
          >
            {isActive ? "Active Run" : "Last Run"}
          </h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div>
              <dt className="text-gray-500">Project</dt>
              <dd className="font-medium text-gray-900">{run.project}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Wave</dt>
              <dd className="font-medium text-gray-900">{run.wave}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Provider</dt>
              <dd className="font-medium capitalize text-gray-900">
                {run.provider}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Status</dt>
              <dd>
                <StatusBadge status={run.status} />
              </dd>
            </div>
          </dl>

          {isActive && (
            <div className="mt-4 flex flex-wrap gap-2">
              {run.status === "running" && (
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => void handlePause(run.run_id)}
                  className="rounded border border-gray-300 px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
                >
                  Pause
                </button>
              )}
              {run.status === "paused" && (
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => void handleResume(run.run_id)}
                  className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
                >
                  Resume
                </button>
              )}
              <button
                type="button"
                disabled={acting}
                onClick={() => void handleStop(run.run_id)}
                className="rounded border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                Stop
              </button>
            </div>
          )}
        </section>
      )}

      {/* Start form — visible only when no active run */}
      {!isActive && (
        <section aria-labelledby="start-heading">
          <h2
            id="start-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500"
          >
            Start a Run
          </h2>
          {openWaves.length === 0 ? (
            <EmptyState
              message="No open waves available. Open a milestone in GitHub to start a run."
              action={
                githubMilestonesUrl ? (
                  <a
                    href={githubMilestonesUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Open GitHub milestones ↗
                  </a>
                ) : undefined
              }
            />
          ) : (
            <form
              onSubmit={(e) => void handleStart(e)}
              aria-busy={acting}
              className="space-y-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div>
                <label
                  htmlFor="run-wave"
                  className="mb-1 block text-sm font-medium text-gray-700"
                >
                  Wave
                </label>
                <select
                  id="run-wave"
                  name="wave"
                  required
                  defaultValue=""
                  className="w-full rounded border border-gray-300 px-3 py-2 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                >
                  <option value="" disabled>
                    Select a wave…
                  </option>
                  {openWaves.map((w) => (
                    <option key={w.name} value={w.name}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </div>

              {providers.length === 0 ? (
                <p className="text-sm text-gray-500">
                  No providers available — check backend configuration.
                </p>
              ) : (
                <div>
                  <label
                    htmlFor="run-provider"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Provider
                  </label>
                  <select
                    id="run-provider"
                    name="provider"
                    defaultValue={providers[0]}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                  >
                    {providers.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <button
                type="submit"
                disabled={acting}
                className="w-full rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {acting ? "Starting…" : "Start run"}
              </button>
            </form>
          )}
        </section>
      )}
    </PopulatedState>
  );
}
