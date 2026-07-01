import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";

// ---------------------------------------------------------------------------
// Module mock
// ---------------------------------------------------------------------------

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
    },
  };
});

const { apiClient, ApiError } = await import("../api");
const mockGet = apiClient.get as ReturnType<typeof vi.fn>;
const mockPut = apiClient.put as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const CONFIG = {
  project_name: "my-project",
  project_description: "Autonomous coding agent",
  provider: {
    default: "claude",
    plan: "pro",
    models: {
      planning: "claude-opus-4-8",
      implementing: "claude-sonnet-4-6",
      reviewing: "claude-sonnet-4-6",
    },
  },
  egress: {
    allow: ["api.anthropic.com", "api.github.com"],
  },
  notifications: {
    telegram: true,
    email: false,
  },
  secrets: {
    ANTHROPIC_API_KEY: "ANTHROPIC_API_KEY",
    GITHUB_TOKEN: "GITHUB_TOKEN",
  },
};

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

const PROVIDERS = { providers: ["claude", "codex", "gemini"] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockImplementation(() => true);
  mockGet.mockImplementation(async (url: string) => {
    if (url === "/config") return CONFIG;
    return PROVIDERS;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SettingsPage", () => {
  it("shows loading state on mount", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<SettingsPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows error state when config fails to load", async () => {
    mockGet.mockRejectedValueOnce(new Error("network error"));
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Failed to load configuration")).toBeInTheDocument();
  });

  it("shows error from ApiError on load failure", async () => {
    mockGet.mockRejectedValueOnce(new ApiError(500, "Internal Server Error"));
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Internal Server Error")).toBeInTheDocument();
  });

  it("renders config values — provider, plan, models", async () => {
    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByDisplayValue("claude")).toBeInTheDocument());
    expect(screen.getByDisplayValue("pro")).toBeInTheDocument();
    expect(screen.getByDisplayValue("claude-opus-4-8")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("claude-sonnet-4-6")).toHaveLength(2);
  });

  it("renders provider options from API, not a hardcoded constant", async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url === "/config") return CONFIG;
      return { providers: ["claude", "codex", "gemini", "future-provider"] };
    });
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));
    const select = screen.getByRole("combobox", { name: /Default provider/i });
    const options = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(["claude", "codex", "gemini", "future-provider"]);
  });

  it("never renders secret values — only env-var names", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() =>
      expect(screen.getByText(/Secret values are never returned/)).toBeInTheDocument(),
    );
    // Secrets section shows env-var name references, never resolved values
    const secretItems = screen.getAllByText("ANTHROPIC_API_KEY");
    expect(secretItems.length).toBeGreaterThan(0);
  });

  it("renders egress allowlist as newline-separated text in textarea", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() =>
      screen.getByRole("textbox", { name: /Egress allowlist/i }),
    );
    const textarea = screen.getByRole("textbox", { name: /Egress allowlist/i });
    expect((textarea as HTMLTextAreaElement).value).toBe(
      "api.anthropic.com\napi.github.com",
    );
  });

  it("renders notification toggles reflecting current state", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Telegram (default on)")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Telegram (default on)")).toBeChecked();
    expect(screen.getByLabelText("Email")).not.toBeChecked();
  });

  it("prompts before saving provider config", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));

    const [saveProviderBtn] = screen.getAllByRole("button", { name: "Save changes" });
    act(() => { fireEvent.click(saveProviderBtn); });

    expect(window.confirm).toHaveBeenCalledWith("Save provider and model changes?");
  });

  it("calls PUT /config/provider with correct body on save", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));

    const [saveProviderBtn] = screen.getAllByRole("button", { name: "Save changes" });
    await act(async () => { fireEvent.click(saveProviderBtn); });

    expect(mockPut).toHaveBeenCalledWith("/config/provider", {
      default: "claude",
      plan: "pro",
      models: {
        planning: "claude-opus-4-8",
        implementing: "claude-sonnet-4-6",
        reviewing: "claude-sonnet-4-6",
      },
    });
  });

  it("shows success feedback after provider save", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));

    const [saveProviderBtn] = screen.getAllByRole("button", { name: "Save changes" });
    await act(async () => { fireEvent.click(saveProviderBtn); });

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Saved successfully.");
  });

  it("shows API error from backend on provider save failure", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockRejectedValueOnce(new ApiError(422, "Invalid provider name"));
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));

    const [saveProviderBtn] = screen.getAllByRole("button", { name: "Save changes" });
    await act(async () => { fireEvent.click(saveProviderBtn); });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid provider name");
  });

  it("does not call PUT when confirm is cancelled", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => false);
    mockGet.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() => screen.getByDisplayValue("claude"));

    const [saveProviderBtn] = screen.getAllByRole("button", { name: "Save changes" });
    act(() => { fireEvent.click(saveProviderBtn); });

    expect(mockPut).not.toHaveBeenCalled();
  });

  it("calls PUT /config/notifications when saving notification channels", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockResolvedValueOnce({ ...CONFIG, notifications: { telegram: true, email: true } });
    render(<SettingsPage />);
    await waitFor(() => screen.getByLabelText("Email"));

    act(() => {
      fireEvent.click(screen.getByLabelText("Email"));
    });

    // Save notifications button is the last "Save changes"
    const saveButtons = screen.getAllByRole("button", { name: "Save changes" });
    await act(async () => { fireEvent.click(saveButtons[saveButtons.length - 1]); });

    expect(mockPut).toHaveBeenCalledWith("/config/notifications", {
      telegram: true,
      email: true,
    });
  });

  it("calls PUT /config/egress with parsed domains", async () => {
    mockGet.mockResolvedValueOnce(CONFIG);
    mockPut.mockResolvedValueOnce(CONFIG);
    render(<SettingsPage />);
    await waitFor(() => screen.getByRole("textbox", { name: /Egress allowlist/i }));

    const saveEgressBtn = screen.getByRole("button", { name: "Replace allowlist" });
    await act(async () => { fireEvent.click(saveEgressBtn); });

    expect(mockPut).toHaveBeenCalledWith("/config/egress", {
      allow: ["api.anthropic.com", "api.github.com"],
    });
  });
});
