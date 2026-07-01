import { useEffect, useReducer, useRef } from "react";
import { API_BASE, ApiError, apiClient, connectSse } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PopulatedState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (mirroring docs/api.md SSE event shapes)
// ---------------------------------------------------------------------------

interface RunStateEvent {
  run_id: number;
  wave: string;
  project: string;
  provider: string;
  status: string;
}

interface IssueStartedEvent {
  run_id: number;
  issue_number: number;
  role: string;
}

interface NormalisedEvent {
  kind: "reasoning" | "tool_call" | "tool_result" | "output";
  content: string;
  tool_name?: string;
  timestamp: number;
}

interface SessionEventPayload {
  run_id: number;
  issue_number: number;
  role: string;
  event: NormalisedEvent;
}

interface IssueCompletedEvent {
  run_id: number;
  issue_number: number;
  outcome: "completed" | "blocked" | "error";
}

interface RunStatus {
  active: boolean;
  run: { run_id: number } | null;
}

// ---------------------------------------------------------------------------
// Log (capped to avoid unbounded growth)
// ---------------------------------------------------------------------------

const MAX_LOG = 200;
let _nextKey = 0;

interface LogEntry {
  key: number;
  eventType: string;
  summary: string;
}

function makeSummary(eventType: string, data: unknown): string {
  switch (eventType) {
    case "run_state": {
      const d = data as RunStateEvent;
      return `Status: ${d.status} — ${d.wave} (${d.project})`;
    }
    case "issue_started": {
      const d = data as IssueStartedEvent;
      return `Issue #${d.issue_number} started (${d.role})`;
    }
    case "session_event": {
      const d = data as SessionEventPayload;
      const ev = d.event;
      if (ev.tool_name) return `[${ev.kind}] ${ev.tool_name}`;
      const preview = ev.content.slice(0, 80);
      return `[${ev.kind}] ${preview}${ev.content.length > 80 ? "…" : ""}`;
    }
    case "issue_completed": {
      const d = data as IssueCompletedEvent;
      return `Issue #${d.issue_number} ${d.outcome}`;
    }
    case "run_ended":
      return "Run ended";
    default:
      return eventType;
  }
}

function appendLog(log: LogEntry[], eventType: string, data: unknown): LogEntry[] {
  const entry: LogEntry = {
    key: ++_nextKey,
    eventType,
    summary: makeSummary(eventType, data),
  };
  const next = [...log, entry];
  return next.length > MAX_LOG ? next.slice(next.length - MAX_LOG) : next;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type ConnStatus = "connecting" | "live" | "reconnecting" | "ended";

type PageState =
  | { phase: "loading" }
  | { phase: "no_run" }
  | { phase: "error"; message: string }
  | {
      phase: "streaming";
      runId: number;
      runInfo: RunStateEvent | null;
      issueContext: { number: number; role: string } | null;
      log: LogEntry[];
      connStatus: ConnStatus;
    };

type PageAction =
  | { type: "no_run" }
  | { type: "fetch_error"; message: string }
  | { type: "run_found"; runId: number }
  | { type: "run_state"; data: RunStateEvent }
  | { type: "issue_started"; data: IssueStartedEvent }
  | { type: "session_event"; data: SessionEventPayload }
  | { type: "issue_completed"; data: IssueCompletedEvent }
  | { type: "run_ended" }
  | { type: "sse_error" };

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "no_run":
      return { phase: "no_run" };
    case "fetch_error":
      return { phase: "error", message: action.message };
    case "run_found":
      return {
        phase: "streaming",
        runId: action.runId,
        runInfo: null,
        issueContext: null,
        log: [],
        connStatus: "connecting",
      };
    case "run_state":
      if (state.phase !== "streaming") return state;
      return {
        ...state,
        runInfo: action.data,
        connStatus: "live",
        log: appendLog(state.log, "run_state", action.data),
      };
    case "issue_started":
      if (state.phase !== "streaming") return state;
      return {
        ...state,
        issueContext: { number: action.data.issue_number, role: action.data.role },
        log: appendLog(state.log, "issue_started", action.data),
      };
    case "session_event":
      if (state.phase !== "streaming") return state;
      return {
        ...state,
        log: appendLog(state.log, "session_event", action.data),
      };
    case "issue_completed":
      if (state.phase !== "streaming") return state;
      return {
        ...state,
        issueContext: null,
        log: appendLog(state.log, "issue_completed", action.data),
      };
    case "run_ended":
      if (state.phase !== "streaming") return state;
      return {
        ...state,
        connStatus: "ended",
        log: appendLog(state.log, "run_ended", null),
      };
    case "sse_error":
      if (state.phase !== "streaming") return state;
      return { ...state, connStatus: "reconnecting" };
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const CONN_BADGE: Record<ConnStatus, { label: string; cls: string }> = {
  connecting: { label: "Connecting…", cls: "bg-yellow-100 text-yellow-800" },
  live: { label: "Live", cls: "bg-green-100 text-green-800" },
  reconnecting: { label: "Reconnecting…", cls: "bg-orange-100 text-orange-800" },
  ended: { label: "Ended", cls: "bg-gray-100 text-gray-600" },
};

function ConnStatusBadge({ status }: { status: ConnStatus }) {
  const { label, cls } = CONN_BADGE[status];
  return (
    <span
      role="status"
      aria-live="polite"
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  run_state: "text-blue-600",
  issue_started: "text-green-700",
  issue_completed: "text-purple-700",
  run_ended: "text-gray-500",
  session_event: "text-gray-600",
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function LiveProgressPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });
  const disconnectRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function setup() {
      try {
        const res = await apiClient.get<RunStatus>("/runs/status", controller.signal);
        if (controller.signal.aborted) return;

        if (!res.active || !res.run) {
          dispatch({ type: "no_run" });
          return;
        }

        const { run_id } = res.run;
        dispatch({ type: "run_found", runId: run_id });

        const url = `${API_BASE}/runs/${run_id}/progress`;
        disconnectRef.current = connectSse(
          url,
          () => { /* named events only */ },
          () => { dispatch({ type: "sse_error" }); },
          {
            run_state: (ev) => {
              dispatch({ type: "run_state", data: JSON.parse(ev.data) as RunStateEvent });
            },
            issue_started: (ev) => {
              dispatch({ type: "issue_started", data: JSON.parse(ev.data) as IssueStartedEvent });
            },
            session_event: (ev) => {
              dispatch({ type: "session_event", data: JSON.parse(ev.data) as SessionEventPayload });
            },
            issue_completed: (ev) => {
              dispatch({ type: "issue_completed", data: JSON.parse(ev.data) as IssueCompletedEvent });
            },
            run_ended: () => {
              dispatch({ type: "run_ended" });
              disconnectRef.current?.();
              disconnectRef.current = null;
            },
          },
        );
      } catch (err) {
        if (controller.signal.aborted) return;
        dispatch({
          type: "fetch_error",
          message: err instanceof ApiError ? err.message : "Failed to load run status",
        });
      }
    }

    void setup();

    return () => {
      controller.abort();
      disconnectRef.current?.();
      disconnectRef.current = null;
    };
  }, []);

  if (state.phase === "loading") return <LoadingState />;

  if (state.phase === "no_run") {
    return (
      <EmptyState
        message="No active run. Start one from the Runs page."
        action={
          <a
            href="/runs"
            className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
          >
            Go to Runs
          </a>
        }
      />
    );
  }

  if (state.phase === "error") {
    return <ErrorState message={state.message} />;
  }

  const { runInfo, issueContext, log, connStatus } = state;

  return (
    <PopulatedState className="flex h-full flex-col p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Live Progress</h1>
        <ConnStatusBadge status={connStatus} />
      </div>

      {/* Run / issue context */}
      {runInfo && (
        <section
          aria-labelledby="run-context-heading"
          className="mb-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        >
          <h2
            id="run-context-heading"
            className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400"
          >
            Current Run
          </h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <div>
              <dt className="text-gray-500">Wave</dt>
              <dd className="font-medium text-gray-900">{runInfo.wave}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Project</dt>
              <dd className="font-medium text-gray-900">{runInfo.project}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Provider</dt>
              <dd className="font-medium capitalize text-gray-900">{runInfo.provider}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Status</dt>
              <dd className="font-medium capitalize text-gray-900">{runInfo.status}</dd>
            </div>
            {issueContext && (
              <>
                <div>
                  <dt className="text-gray-500">Issue</dt>
                  <dd className="font-medium text-gray-900">#{issueContext.number}</dd>
                </div>
                <div>
                  <dt className="text-gray-500">Role</dt>
                  <dd className="font-medium capitalize text-gray-900">{issueContext.role}</dd>
                </div>
              </>
            )}
          </dl>
        </section>
      )}

      {/* Event log */}
      <section
        aria-labelledby="event-log-heading"
        className="flex min-h-0 flex-1 flex-col rounded-lg border border-gray-200 bg-white shadow-sm"
      >
        <h2
          id="event-log-heading"
          className="border-b border-gray-100 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400"
        >
          Event Log
          {log.length >= MAX_LOG && (
            <span className="ml-2 font-normal normal-case text-gray-400">
              (showing last {MAX_LOG})
            </span>
          )}
        </h2>
        {log.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">Waiting for events…</p>
        ) : (
          <ol
            aria-label="Event log"
            className="flex-1 overflow-auto divide-y divide-gray-50 text-sm"
          >
            {log.map((entry) => (
              <li key={entry.key} className="flex items-baseline gap-3 px-4 py-1.5">
                <span
                  className={`w-24 flex-shrink-0 text-xs font-medium ${EVENT_TYPE_COLORS[entry.eventType] ?? "text-gray-500"}`}
                >
                  {entry.eventType}
                </span>
                <span className="min-w-0 break-words text-gray-700">{entry.summary}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </PopulatedState>
  );
}
