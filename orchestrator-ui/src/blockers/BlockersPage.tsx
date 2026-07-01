import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, apiClient } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PopulatedState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § GET /blockers)
// ---------------------------------------------------------------------------

type BlockerType =
  | "missing_spec"
  | "contract_conflict"
  | "unmet_dependency"
  | "stuck_agent"
  | "other";

interface BlockerRecord {
  id: number;
  run_id: number;
  issue_number: number;
  blocker_type: BlockerType;
  reason: string;
  needed_to_unblock: string;
  status: "parked" | "resolved";
  created_at: string;
  resolved_at: string | null;
  resolution_response: string | null;
}

interface BlockersResponse {
  blockers: BlockerRecord[];
  run_id: number;
}

// ---------------------------------------------------------------------------
// Per-blocker form state
// ---------------------------------------------------------------------------

type FormState =
  | { status: "idle"; text: string }
  | { status: "submitting"; text: string }
  | { status: "success"; resolution: string }
  | { status: "error"; text: string; message: string };

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type PageState =
  | { phase: "loading" }
  | { phase: "no_run" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | {
      phase: "populated";
      blockers: BlockerRecord[];
      run_id: number;
      forms: Record<number, FormState>;
    };

type PageAction =
  | { type: "loaded"; data: BlockersResponse }
  | { type: "load_error"; message: string; isNotFound: boolean }
  | { type: "text_changed"; id: number; text: string }
  | { type: "submit_start"; id: number }
  | { type: "submit_success"; id: number; resolved: BlockerRecord }
  | { type: "submit_error"; id: number; message: string };

function makeInitialForms(blockers: BlockerRecord[]): Record<number, FormState> {
  return Object.fromEntries(blockers.map((b) => [b.id, { status: "idle", text: "" }]));
}

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "loaded": {
      if (action.data.blockers.length === 0) return { phase: "empty" };
      return {
        phase: "populated",
        blockers: action.data.blockers,
        run_id: action.data.run_id,
        forms: makeInitialForms(action.data.blockers),
      };
    }
    case "load_error":
      return action.isNotFound ? { phase: "no_run" } : { phase: "error", message: action.message };
    case "text_changed": {
      if (state.phase !== "populated") return state;
      const form = state.forms[action.id];
      if (!form || form.status === "submitting" || form.status === "success") return state;
      return {
        ...state,
        forms: {
          ...state.forms,
          [action.id]: { status: "idle", text: action.text },
        },
      };
    }
    case "submit_start": {
      if (state.phase !== "populated") return state;
      const form = state.forms[action.id];
      if (!form || form.status !== "idle") return state;
      return {
        ...state,
        forms: { ...state.forms, [action.id]: { status: "submitting", text: form.text } },
      };
    }
    case "submit_success": {
      if (state.phase !== "populated") return state;
      const form = state.forms[action.id];
      const resolution =
        form?.status === "submitting" ? form.text : action.resolved.resolution_response ?? "";
      return {
        ...state,
        blockers: state.blockers.map((b) =>
          b.id === action.id ? action.resolved : b,
        ),
        forms: {
          ...state.forms,
          [action.id]: { status: "success", resolution },
        },
      };
    }
    case "submit_error": {
      if (state.phase !== "populated") return state;
      const form = state.forms[action.id];
      const text = form?.status === "submitting" ? form.text : "";
      return {
        ...state,
        forms: {
          ...state.forms,
          [action.id]: { status: "error", text, message: action.message },
        },
      };
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBlockerType(t: BlockerType): string {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// ---------------------------------------------------------------------------
// Blocker card
// ---------------------------------------------------------------------------

interface CardProps {
  blocker: BlockerRecord;
  form: FormState;
  onTextChange: (text: string) => void;
  onSubmit: () => void;
}

function BlockerCard({ blocker, form, onTextChange, onSubmit }: CardProps) {
  const resolved = blocker.status === "resolved" || form.status === "success";
  const resolutionRef = useRef<HTMLDivElement>(null);

  // Move focus to the resolved section so keyboard/SR users don't lose their place.
  useEffect(() => {
    if (form.status === "success") {
      resolutionRef.current?.focus();
    }
  }, [form.status]);

  return (
    <article
      aria-label={`Blocker for issue #${blocker.issue_number}`}
      className={`rounded-lg border p-4 shadow-sm ${
        resolved ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50"
      }`}
    >
      {/* Header */}
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Issue #{blocker.issue_number}
          </span>
          <h2 className="text-sm font-semibold text-gray-900">
            {formatBlockerType(blocker.blocker_type)}
          </h2>
        </div>
        {resolved ? (
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
            Resolved
          </span>
        ) : (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            Parked
          </span>
        )}
      </div>

      {/* Details */}
      <div className="mb-3 space-y-1 text-sm text-gray-700">
        <p>
          <span className="font-medium">Reason: </span>
          {blocker.reason}
        </p>
        {!resolved && (
          <p>
            <span className="font-medium">Needed to unblock: </span>
            {blocker.needed_to_unblock}
          </p>
        )}
        <p className="text-xs text-gray-500">Parked {formatDate(blocker.created_at)}</p>
      </div>

      {/* Resolution area */}
      {resolved ? (
        <div
          ref={resolutionRef}
          tabIndex={-1}
          aria-label="Blocker resolved — your response has been submitted"
          className="rounded border border-green-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-indigo-500"
        >
          <span className="font-medium text-green-700">Response: </span>
          {blocker.resolution_response ?? (form.status === "success" ? form.resolution : "")}
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
          aria-label={`Respond to blocker for issue #${blocker.issue_number}`}
        >
          <label
            htmlFor={`response-${blocker.id}`}
            className="mb-1 block text-xs font-medium text-gray-700"
          >
            Your response
          </label>
          <textarea
            id={`response-${blocker.id}`}
            rows={3}
            value={form.status === "idle" || form.status === "error" ? form.text : ""}
            onChange={(e) => onTextChange(e.target.value)}
            disabled={form.status === "submitting"}
            required
            placeholder={blocker.needed_to_unblock}
            className="mb-2 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 disabled:opacity-50"
          />
          {form.status === "error" && (
            <p role="alert" className="mb-2 text-xs text-red-600">
              {form.message}
            </p>
          )}
          <button
            type="submit"
            disabled={
              form.status === "submitting" ||
              (form.status === "idle" && form.text.trim() === "") ||
              (form.status === "error" && form.text.trim() === "")
            }
            className="rounded bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-40"
          >
            {form.status === "submitting" ? "Sending…" : "Send response"}
          </button>
        </form>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 30_000;

export function BlockersPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });

  const fetchBlockers = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await apiClient.get<BlockersResponse>("/blockers", signal);
      dispatch({ type: "loaded", data });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({
        type: "load_error",
        message: err instanceof ApiError ? err.message : "Failed to load blockers",
        isNotFound: err instanceof ApiError && err.status === 404,
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchBlockers(controller.signal);
    const id = setInterval(() => {
      void fetchBlockers(controller.signal);
    }, POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [fetchBlockers]);

  async function handleSubmit(blocker: BlockerRecord) {
    if (state.phase !== "populated") return;
    const form = state.forms[blocker.id];
    if (!form || form.status !== "idle" || form.text.trim() === "") return;

    dispatch({ type: "submit_start", id: blocker.id });
    try {
      const resolved = await apiClient.post<BlockerRecord>(
        `/blockers/${blocker.issue_number}/resolve`,
        { response: form.text.trim() },
      );
      dispatch({ type: "submit_success", id: blocker.id, resolved });
    } catch (err) {
      dispatch({
        type: "submit_error",
        id: blocker.id,
        message: err instanceof ApiError ? err.message : "Failed to send response",
      });
    }
  }

  if (state.phase === "loading") return <LoadingState />;

  if (state.phase === "no_run") {
    return <EmptyState message="No active run — start one from the Runs page to see blockers." />;
  }

  if (state.phase === "empty") {
    return (
      <EmptyState message="No blockers — the run is healthy and progressing normally." />
    );
  }

  if (state.phase === "error") {
    return (
      <ErrorState
        message={state.message}
        retry={() => { void fetchBlockers(); }}
      />
    );
  }

  const { blockers, forms } = state;

  return (
    <PopulatedState className="p-6">
      <h1 className="mb-4 text-xl font-semibold text-gray-900">
        Blockers
        <span className="ml-2 text-base font-normal text-gray-500">
          ({blockers.filter((b) => b.status === "parked").length} parked)
        </span>
      </h1>
      <div className="space-y-4">
        {blockers.map((blocker) => (
          <BlockerCard
            key={blocker.id}
            blocker={blocker}
            form={forms[blocker.id] ?? { status: "idle", text: "" }}
            onTextChange={(text) => dispatch({ type: "text_changed", id: blocker.id, text })}
            onSubmit={() => { void handleSubmit(blocker); }}
          />
        ))}
      </div>
    </PopulatedState>
  );
}
