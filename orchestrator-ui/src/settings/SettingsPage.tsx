import { useCallback, useEffect, useReducer } from "react";
import { ApiError, apiClient } from "../api";
import { ErrorState, LoadingState } from "../components/StateViews";

// ---------------------------------------------------------------------------
// Types (matching docs/api.md § GET /config)
// ---------------------------------------------------------------------------

interface ProviderConfig {
  default: string;
  plan: string;
  models: {
    planning: string;
    implementing: string;
    reviewing: string;
  };
}

interface ConfigResponse {
  project_name: string;
  project_description: string;
  provider: ProviderConfig;
  egress: { allow: string[] };
  notifications: { telegram: boolean; email: boolean };
  secrets: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Local edit shapes
// ---------------------------------------------------------------------------

interface ProviderEdit {
  default: string;
  plan: string;
  planningModel: string;
  implementingModel: string;
  reviewingModel: string;
}

interface EgressEdit {
  allowText: string; // newline-separated domains
}

interface NotifEdit {
  telegram: boolean;
  email: boolean;
}

type SectionStatus = "idle" | "saving" | "success" | "error";

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

interface PopulatedState {
  phase: "populated";
  config: ConfigResponse;
  providers: string[];
  provider: ProviderEdit;
  providerStatus: SectionStatus;
  providerError: string;
  egress: EgressEdit;
  egressStatus: SectionStatus;
  egressError: string;
  notif: NotifEdit;
  notifStatus: SectionStatus;
  notifError: string;
}

type PageState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | PopulatedState;

type PageAction =
  | { type: "loaded"; config: ConfigResponse; providers: string[] }
  | { type: "load_error"; message: string }
  | { type: "provider_change"; field: keyof ProviderEdit; value: string }
  | { type: "provider_saving" }
  | { type: "provider_saved"; config: ConfigResponse }
  | { type: "provider_error"; message: string }
  | { type: "egress_change"; value: string }
  | { type: "egress_saving" }
  | { type: "egress_saved"; config: ConfigResponse }
  | { type: "egress_error"; message: string }
  | { type: "notif_change"; field: keyof NotifEdit; value: boolean }
  | { type: "notif_saving" }
  | { type: "notif_saved"; config: ConfigResponse }
  | { type: "notif_error"; message: string };

function configToProviderEdit(c: ConfigResponse): ProviderEdit {
  return {
    default: c.provider.default,
    plan: c.provider.plan,
    planningModel: c.provider.models.planning,
    implementingModel: c.provider.models.implementing,
    reviewingModel: c.provider.models.reviewing,
  };
}

function configToEgressEdit(c: ConfigResponse): EgressEdit {
  return { allowText: c.egress.allow.join("\n") };
}

function configToNotifEdit(c: ConfigResponse): NotifEdit {
  return { telegram: c.notifications.telegram, email: c.notifications.email };
}

function reducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    case "loaded":
      return {
        phase: "populated",
        config: action.config,
        providers: action.providers,
        provider: configToProviderEdit(action.config),
        providerStatus: "idle",
        providerError: "",
        egress: configToEgressEdit(action.config),
        egressStatus: "idle",
        egressError: "",
        notif: configToNotifEdit(action.config),
        notifStatus: "idle",
        notifError: "",
      };
    case "load_error":
      return { phase: "error", message: action.message };
    case "provider_change":
      if (state.phase !== "populated") return state;
      return { ...state, provider: { ...state.provider, [action.field]: action.value } };
    case "provider_saving":
      if (state.phase !== "populated") return state;
      return { ...state, providerStatus: "saving", providerError: "" };
    case "provider_saved":
      if (state.phase !== "populated") return state;
      return {
        ...state,
        config: action.config,
        provider: configToProviderEdit(action.config),
        providerStatus: "success",
        providerError: "",
      };
    case "provider_error":
      if (state.phase !== "populated") return state;
      return { ...state, providerStatus: "error", providerError: action.message };
    case "egress_change":
      if (state.phase !== "populated") return state;
      return { ...state, egress: { allowText: action.value } };
    case "egress_saving":
      if (state.phase !== "populated") return state;
      return { ...state, egressStatus: "saving", egressError: "" };
    case "egress_saved":
      if (state.phase !== "populated") return state;
      return {
        ...state,
        config: action.config,
        egress: configToEgressEdit(action.config),
        egressStatus: "success",
        egressError: "",
      };
    case "egress_error":
      if (state.phase !== "populated") return state;
      return { ...state, egressStatus: "error", egressError: action.message };
    case "notif_change":
      if (state.phase !== "populated") return state;
      return { ...state, notif: { ...state.notif, [action.field]: action.value } };
    case "notif_saving":
      if (state.phase !== "populated") return state;
      return { ...state, notifStatus: "saving", notifError: "" };
    case "notif_saved":
      if (state.phase !== "populated") return state;
      return {
        ...state,
        config: action.config,
        notif: configToNotifEdit(action.config),
        notifStatus: "success",
        notifError: "",
      };
    case "notif_error":
      if (state.phase !== "populated") return state;
      return { ...state, notifStatus: "error", notifError: action.message };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ title }: { title: string }) {
  return (
    <h2 className="mb-3 text-base font-semibold text-gray-900">{title}</h2>
  );
}

function SaveButton({
  status,
  onClick,
  label = "Save changes",
}: {
  status: SectionStatus;
  onClick: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={status === "saving"}
      className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
    >
      {status === "saving" ? "Saving…" : label}
    </button>
  );
}

function SectionFeedback({
  status,
  error,
}: {
  status: SectionStatus;
  error: string;
}) {
  if (status === "success") {
    return (
      <p role="status" className="text-sm text-green-700">
        Saved successfully.
      </p>
    );
  }
  if (status === "error") {
    return (
      <p role="alert" className="text-sm text-red-700">
        {error}
      </p>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SettingsPage() {
  const [state, dispatch] = useReducer(reducer, { phase: "loading" });

  const fetchConfig = useCallback(async (signal?: AbortSignal) => {
    try {
      const [config, providersResp] = await Promise.all([
        apiClient.get<ConfigResponse>("/config", signal),
        apiClient.get<{ providers: string[] }>("/config/providers", signal),
      ]);
      dispatch({ type: "loaded", config, providers: providersResp.providers });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({
        type: "load_error",
        message: err instanceof ApiError ? err.message : "Failed to load configuration",
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchConfig(controller.signal);
    return () => { controller.abort(); };
  }, [fetchConfig]);

  if (state.phase === "loading") return <LoadingState />;
  if (state.phase === "error") {
    return (
      <ErrorState
        message={state.message}
        retry={() => { void fetchConfig(); }}
      />
    );
  }

  const { config, providers, provider, providerStatus, providerError, egress, egressStatus, egressError, notif, notifStatus, notifError } = state;

  // ---- provider save ----
  async function saveProvider() {
    if (!window.confirm("Save provider and model changes?")) return;
    dispatch({ type: "provider_saving" });
    try {
      const body = {
        default: provider.default,
        plan: provider.plan,
        models: {
          planning: provider.planningModel,
          implementing: provider.implementingModel,
          reviewing: provider.reviewingModel,
        },
      };
      const data = await apiClient.put<ConfigResponse>("/config/provider", body);
      dispatch({ type: "provider_saved", config: data });
    } catch (err) {
      dispatch({
        type: "provider_error",
        message: err instanceof ApiError ? err.message : "Failed to save provider config",
      });
    }
  }

  // ---- egress save ----
  async function saveEgress() {
    if (!window.confirm("Replace the egress allowlist with these domains?")) return;
    dispatch({ type: "egress_saving" });
    try {
      const allow = egress.allowText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const data = await apiClient.put<ConfigResponse>("/config/egress", { allow });
      dispatch({ type: "egress_saved", config: data });
    } catch (err) {
      dispatch({
        type: "egress_error",
        message: err instanceof ApiError ? err.message : "Failed to save egress config",
      });
    }
  }

  // ---- notifications save ----
  async function saveNotif() {
    if (!window.confirm("Save notification channel settings?")) return;
    dispatch({ type: "notif_saving" });
    try {
      const data = await apiClient.put<ConfigResponse>("/config/notifications", {
        telegram: notif.telegram,
        email: notif.email,
      });
      dispatch({ type: "notif_saved", config: data });
    } catch (err) {
      dispatch({
        type: "notif_error",
        message: err instanceof ApiError ? err.message : "Failed to save notification settings",
      });
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 p-6">
      <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500">
        <strong>Project:</strong> {config.project_name}
        {config.project_description && (
          <> — {config.project_description}</>
        )}
      </p>

      {/* ---- Provider / model mapping ---- */}
      <section aria-label="Provider and model configuration" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <SectionHeader title="Provider & models" />
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <label htmlFor="provider-default" className="block text-xs font-medium text-gray-700">
                Default provider
              </label>
              <select
                id="provider-default"
                value={provider.default}
                onChange={(e) => dispatch({ type: "provider_change", field: "default", value: e.target.value })}
                className="mt-1 block w-full rounded border border-gray-300 bg-white px-2 py-1.5 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {providers.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="provider-plan" className="block text-xs font-medium text-gray-700">
                Plan
              </label>
              <input
                id="provider-plan"
                type="text"
                value={provider.plan}
                onChange={(e) => dispatch({ type: "provider_change", field: "plan", value: e.target.value })}
                className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(
              [
                { label: "Planning model", field: "planningModel", value: provider.planningModel },
                { label: "Implementing model", field: "implementingModel", value: provider.implementingModel },
                { label: "Reviewing model", field: "reviewingModel", value: provider.reviewingModel },
              ] as { label: string; field: keyof ProviderEdit; value: string }[]
            ).map(({ label, field, value }) => (
              <div key={field}>
                <label htmlFor={`model-${field}`} className="block text-xs font-medium text-gray-700">
                  {label}
                </label>
                <input
                  id={`model-${field}`}
                  type="text"
                  value={value}
                  onChange={(e) =>
                    dispatch({ type: "provider_change", field, value: e.target.value })
                  }
                  className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3 pt-1">
            <SaveButton status={providerStatus} onClick={() => { void saveProvider(); }} />
            <SectionFeedback status={providerStatus} error={providerError} />
          </div>
        </div>
      </section>

      {/* ---- Egress allowlist ---- */}
      <section aria-label="Egress allowlist configuration" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <SectionHeader title="Egress allowlist" />
        <p className="mb-2 text-xs text-gray-500">
          One hostname per line. Replaces the current list on save.
        </p>
        <textarea
          id="egress-allow"
          aria-label="Egress allowlist — one hostname per line"
          rows={5}
          value={egress.allowText}
          onChange={(e) => dispatch({ type: "egress_change", value: e.target.value })}
          className="block w-full rounded border border-gray-300 px-2 py-1.5 font-mono text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          spellCheck={false}
        />
        <div className="mt-2 flex items-center gap-3">
          <SaveButton status={egressStatus} onClick={() => { void saveEgress(); }} label="Replace allowlist" />
          <SectionFeedback status={egressStatus} error={egressError} />
        </div>
      </section>

      {/* ---- Notifications ---- */}
      <section aria-label="Notification channels" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <SectionHeader title="Notifications" />
        <div className="space-y-2">
          {(
            [
              { field: "telegram", label: "Telegram (default on)" },
              { field: "email", label: "Email" },
            ] as { field: keyof NotifEdit; label: string }[]
          ).map(({ field, label }) => (
            <label key={field} className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={notif[field]}
                onChange={(e) =>
                  dispatch({ type: "notif_change", field, value: e.target.checked })
                }
                aria-label={label}
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-gray-800">{label}</span>
            </label>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <SaveButton status={notifStatus} onClick={() => { void saveNotif(); }} />
          <SectionFeedback status={notifStatus} error={notifError} />
        </div>
      </section>

      {/* ---- Secrets (read-only) ---- */}
      <section aria-label="Secret references" className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <SectionHeader title="Secrets" />
        <p className="mb-3 text-xs text-gray-500">
          Secret values are never returned — only the environment variable names used to resolve them.
        </p>
        <dl className="space-y-1">
          {Object.entries(config.secrets).map(([key, envVar]) => (
            <div key={key} className="flex gap-2 text-sm">
              <dt className="w-48 flex-shrink-0 font-medium text-gray-700">{key}</dt>
              <dd className="font-mono text-gray-500">{envVar}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
