import { useCallback, useEffect, useReducer } from "react";
import { ApiError, apiClient } from "../api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PopulatedState,
} from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § GET /prs)
// ---------------------------------------------------------------------------

interface ChecklistItem {
  text: string;
  checked: boolean;
}

interface HandoffPR {
  number: number;
  title: string;
  body: string;
  html_url: string;
  head_branch: string;
  base_branch: string;
  state: string;
  checklist: ChecklistItem[];
}

interface PrsResponse {
  prs: HandoffPR[];
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type PageState =
  | { phase: "loading" }
  | { phase: "empty" }
  | { phase: "error"; message: string }
  | { phase: "populated"; prs: HandoffPR[] };

type PageAction =
  | { type: "loaded"; prs: HandoffPR[] }
  | { type: "load_error"; message: string };

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "loaded":
      return action.prs.length === 0
        ? { phase: "empty" }
        : { phase: "populated", prs: action.prs };
    case "load_error":
      return { phase: "error", message: action.message };
  }
}

// ---------------------------------------------------------------------------
// PR card
// ---------------------------------------------------------------------------

function ChecklistView({ items }: { items: ChecklistItem[] }) {
  if (items.length === 0) return null;
  const done = items.filter((i) => i.checked).length;
  return (
    <section aria-label="Review checklist">
      <div className="mb-1 flex items-center justify-between text-xs text-gray-500">
        <span className="font-medium uppercase tracking-wide">Review checklist</span>
        <span>
          {done}/{items.length} checked
        </span>
      </div>
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-2 text-sm">
            <span
              aria-hidden="true"
              className={`mt-0.5 flex-shrink-0 text-base leading-none ${
                item.checked ? "text-green-600" : "text-gray-400"
              }`}
            >
              {item.checked ? "☑" : "☐"}
            </span>
            <span
              aria-label={`${item.checked ? "Checked" : "Unchecked"}: ${item.text}`}
              className={item.checked ? "text-gray-500 line-through" : "text-gray-800"}
            >
              {item.text}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PrCard({ pr }: { pr: HandoffPR }) {
  const totalItems = pr.checklist.length;
  const checkedItems = pr.checklist.filter((i) => i.checked).length;
  const allChecked = totalItems > 0 && checkedItems === totalItems;

  return (
    <article
      aria-label={`Pull request #${pr.number}: ${pr.title}`}
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
    >
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-100 px-4 py-3">
        <div className="min-w-0">
          <p className="text-base font-semibold text-gray-900">
            #{pr.number} {pr.title}
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            {pr.head_branch} → {pr.base_branch}
          </p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          {allChecked && (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
              Ready to merge
            </span>
          )}
          <a
            href={pr.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
            aria-label={`Review PR #${pr.number}: ${pr.title} on GitHub`}
          >
            Review on GitHub ↗
          </a>
        </div>
      </div>

      {/* Body (plain text — no markdown lib available) */}
      {pr.body && (
        <div className="border-b border-gray-100 px-4 py-3">
          <pre className="whitespace-pre-wrap break-words font-sans text-sm text-gray-700">
            {pr.body}
          </pre>
        </div>
      )}

      {/* Checklist */}
      {pr.checklist.length > 0 && (
        <div className="px-4 py-3">
          <ChecklistView items={pr.checklist} />
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PrsPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });

  const fetchPrs = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await apiClient.get<PrsResponse>("/prs", signal);
      dispatch({ type: "loaded", prs: data.prs });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({
        type: "load_error",
        message: err instanceof ApiError ? err.message : "Failed to load pull requests",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchPrs(controller.signal);
    return () => { controller.abort(); };
  }, [fetchPrs]);

  if (state.phase === "loading") return <LoadingState />;

  if (state.phase === "empty") {
    return <EmptyState message="No hand-off PRs open yet — they appear here once an issue is ready for review." />;
  }

  if (state.phase === "error") {
    return (
      <ErrorState
        message={state.message}
        retry={() => { void fetchPrs(); }}
      />
    );
  }

  const { prs } = state;

  return (
    <PopulatedState className="p-6">
      <h1 className="mb-4 text-xl font-semibold text-gray-900">
        Hand-off PRs
        <span className="ml-2 text-base font-normal text-gray-500">
          ({prs.length} open)
        </span>
      </h1>
      <div className="space-y-4">
        {prs.map((pr) => (
          <PrCard key={pr.number} pr={pr} />
        ))}
      </div>
    </PopulatedState>
  );
}
