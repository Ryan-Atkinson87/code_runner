import { useReducer } from "react";
import { ApiError, apiClient } from "../api";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § POST /profile/propose)
// ---------------------------------------------------------------------------

interface ProposeResponse {
  outcome: "proposed" | "error";
  raw_yaml: string;
  error: string;
}

interface ConfirmResponse {
  written: boolean;
  path: string;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type PageState =
  | { phase: "idle" }
  | { phase: "generating" }
  | { phase: "proposed"; rawYaml: string; actionError: string }
  | { phase: "confirming"; rawYaml: string }
  | { phase: "rejecting"; rawYaml: string }
  | { phase: "confirmed"; path: string }
  | { phase: "rejected" }
  | { phase: "error"; message: string };

type PageAction =
  | { type: "generate_start" }
  | { type: "proposed"; rawYaml: string }
  | { type: "generate_error"; message: string }
  | { type: "confirm_start" }
  | { type: "confirmed"; path: string }
  | { type: "action_error"; message: string; rawYaml: string }
  | { type: "reject_start" }
  | { type: "rejected" }
  | { type: "reset" };

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "generate_start":
      return { phase: "generating" };
    case "proposed":
      return { phase: "proposed", rawYaml: action.rawYaml, actionError: "" };
    case "generate_error":
      return { phase: "error", message: action.message };
    case "confirm_start":
      if (state.phase !== "proposed") return state;
      return { phase: "confirming", rawYaml: state.rawYaml };
    case "confirmed":
      return { phase: "confirmed", path: action.path };
    case "action_error":
      return { phase: "proposed", rawYaml: action.rawYaml, actionError: action.message };
    case "reject_start":
      if (state.phase !== "proposed") return state;
      return { phase: "rejecting", rawYaml: state.rawYaml };
    case "rejected":
      return { phase: "rejected" };
    case "reset":
      return { phase: "idle" };
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ProfilePage() {
  const [state, dispatch] = useReducer(reducer, { phase: "idle" });

  async function handleGenerate() {
    dispatch({ type: "generate_start" });
    try {
      const data = await apiClient.post<ProposeResponse>("/profile/propose");
      if (data.outcome === "error") {
        dispatch({ type: "generate_error", message: data.error || "Profile generation failed" });
      } else {
        dispatch({ type: "proposed", rawYaml: data.raw_yaml });
      }
    } catch (err) {
      dispatch({
        type: "generate_error",
        message: err instanceof ApiError ? err.message : "Failed to generate profile",
      });
    }
  }

  async function handleConfirm(rawYaml: string) {
    if (!window.confirm("Write this profile to execution-profile.yaml? This cannot be undone from the UI.")) return;
    dispatch({ type: "confirm_start" });
    try {
      const data = await apiClient.post<ConfirmResponse>("/profile/confirm");
      dispatch({ type: "confirmed", path: data.path });
    } catch (err) {
      dispatch({
        type: "action_error",
        rawYaml,
        message: err instanceof ApiError ? err.message : "Failed to write profile",
      });
    }
  }

  async function handleReject(rawYaml: string) {
    if (!window.confirm("Discard this proposal? Nothing will be written.")) return;
    dispatch({ type: "reject_start" });
    try {
      await apiClient.post("/profile/reject");
      dispatch({ type: "rejected" });
    } catch (err) {
      dispatch({
        type: "action_error",
        rawYaml,
        message: err instanceof ApiError ? err.message : "Failed to reject profile",
      });
    }
  }

  // ---- idle ----
  if (state.phase === "idle") {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="mb-2 text-xl font-semibold text-gray-900">Profile generation</h1>
        <p className="mb-6 text-sm text-gray-600">
          Run a tech-lead session to propose an <code>execution-profile.yaml</code> for this
          project. The proposed profile is shown for review before anything is written to disk.
        </p>
        <button
          type="button"
          onClick={() => { void handleGenerate(); }}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Generate profile
        </button>
      </div>
    );
  }

  // ---- generating ----
  if (state.phase === "generating") {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="mb-4 text-xl font-semibold text-gray-900">Profile generation</h1>
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-3 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-800"
        >
          <svg
            aria-hidden="true"
            className="h-5 w-5 animate-spin text-indigo-600"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          Generating execution profile — this may take a few minutes…
        </div>
      </div>
    );
  }

  // ---- error ----
  if (state.phase === "error") {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="mb-4 text-xl font-semibold text-gray-900">Profile generation</h1>
        <div role="alert" className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {state.message}
        </div>
        <button
          type="button"
          onClick={() => dispatch({ type: "reset" })}
          className="rounded border border-gray-300 bg-white px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Try again
        </button>
      </div>
    );
  }

  // ---- confirmed ----
  if (state.phase === "confirmed") {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="mb-4 text-xl font-semibold text-gray-900">Profile generation</h1>
        <div role="status" className="mb-4 rounded border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          Profile written to <code>{state.path}</code>.
        </div>
        <button
          type="button"
          onClick={() => dispatch({ type: "reset" })}
          className="rounded border border-gray-300 bg-white px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Generate another
        </button>
      </div>
    );
  }

  // ---- rejected ----
  if (state.phase === "rejected") {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="mb-4 text-xl font-semibold text-gray-900">Profile generation</h1>
        <div role="status" className="mb-4 rounded border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700">
          Proposal discarded. Nothing was written.
        </div>
        <button
          type="button"
          onClick={() => dispatch({ type: "reset" })}
          className="rounded border border-gray-300 bg-white px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Generate another
        </button>
      </div>
    );
  }

  // ---- proposed / confirming / rejecting ----
  const rawYaml = state.rawYaml;
  const actionError = state.phase === "proposed" ? state.actionError : "";
  const isActing = state.phase === "confirming" || state.phase === "rejecting";

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-2 text-xl font-semibold text-gray-900">Review proposed profile</h1>
      <p className="mb-4 text-sm text-gray-600">
        Review the proposed <code>execution-profile.yaml</code> below. Confirm to write it to
        disk, or reject to discard it — nothing is written until you confirm.
      </p>

      <div className="mb-4 rounded border border-gray-200 bg-gray-50">
        <div className="border-b border-gray-200 px-3 py-2 text-xs font-medium text-gray-500">
          execution-profile.yaml (proposed)
        </div>
        <pre
          aria-label="Proposed execution-profile.yaml content"
          className="overflow-auto p-4 text-sm text-gray-800"
        >
          {rawYaml}
        </pre>
      </div>

      {actionError && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {actionError}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => { void handleConfirm(rawYaml); }}
          disabled={isActing}
          className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {state.phase === "confirming" ? "Writing…" : "Confirm & write"}
        </button>
        <button
          type="button"
          onClick={() => { void handleReject(rawYaml); }}
          disabled={isActing}
          className="rounded border border-red-300 bg-white px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
        >
          {state.phase === "rejecting" ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </div>
  );
}
