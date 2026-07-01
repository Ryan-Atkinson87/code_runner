import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EfficiencyReport } from "./ReportsPage";
import { ReportsPage } from "./ReportsPage";

// ---------------------------------------------------------------------------
// Module mock
// ---------------------------------------------------------------------------

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    apiClient: {
      get: vi.fn(),
    },
  };
});

const { apiClient } = await import("../api");
const mockGet = apiClient.get as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const WAVES_RESPONSE = {
  waves: [
    { name: "Foundations", milestone_number: 1, state: "closed" },
    { name: "Observability + UI", milestone_number: 6, state: "open" },
  ],
};

const REPORT: EfficiencyReport = {
  scope: "all",
  generated_at: "2026-06-30T12:00:00Z",
  total_sessions: 42,
  total_cost_usd: 1.23,
  tokens: {
    by_issue: { "47": 14200 },
    by_role: { implementor: 18300, orchestrator: 4000 },
    by_skill: { implement: 15000, review: 7300 },
    by_wave: { "Observability + UI": 22300 },
    total_in: 17800,
    total_out: 4500,
  },
  retries: {
    total_retries: 5,
    avg_per_session: 0.12,
    high_retry_skills: ["implement"],
  },
  model_outcomes: [
    {
      model: "claude-sonnet-4-6",
      session_count: 38,
      completed_count: 35,
      blocked_count: 2,
      error_count: 1,
      total_tokens: 19800,
      total_cost_usd: 1.1,
      completion_rate: 0.92,
    },
  ],
  regressions: [
    {
      metric: "tokens_per_issue",
      earlier_month: "2026-05",
      later_month: "2026-06",
      earlier_value: 400.0,
      later_value: 460.0,
      pct_increase: 15.0,
    },
  ],
  suggestions: [
    {
      category: "verbose_skill",
      message:
        "Skill 'implement' averages 9800 input tokens/session (3.2× median).",
    },
  ],
};

const EMPTY_REPORT: EfficiencyReport = {
  ...REPORT,
  total_sessions: 0,
};

const WAVE_REPORT: EfficiencyReport = {
  ...REPORT,
  scope: "wave:Observability + UI",
};

const MONTH_REPORT: EfficiencyReport = {
  ...REPORT,
  scope: "month:2026-06",
};

// ---------------------------------------------------------------------------
// Default mock: waves always resolve; report resolves based on URL.
// ---------------------------------------------------------------------------

function setupMocks(reportResponse: EfficiencyReport | "error" = REPORT) {
  mockGet.mockImplementation((url: string) => {
    if (url === "/runs/waves") return Promise.resolve(WAVES_RESPONSE);
    if (url.startsWith("/reports")) {
      if (reportResponse === "error") {
        return Promise.reject(new Error("Server error"));
      }
      return Promise.resolve(reportResponse);
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ReportsPage", () => {
  describe("All Data scope (default)", () => {
    it("shows loading state on mount", () => {
      mockGet.mockImplementation(() => new Promise(() => {}));
      render(<ReportsPage />);
      expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    });

    it("renders summary cards with session count and cost", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("42")).toBeInTheDocument(),
      );
      expect(screen.getByText("$1.2300")).toBeInTheDocument();
    });

    it("renders token totals (in + out)", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText(/17,800 in \/ 4,500 out/)).toBeInTheDocument(),
      );
    });

    it("renders tokens-by-role breakdown table", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("Tokens by Role")).toBeInTheDocument(),
      );
      expect(screen.getByText("implementor")).toBeInTheDocument();
      expect(screen.getByText("orchestrator")).toBeInTheDocument();
    });

    it("renders tokens-by-skill breakdown table", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("Tokens by Skill")).toBeInTheDocument(),
      );
      // "review" only appears in the by_skill table (not in retries)
      expect(screen.getByText("review")).toBeInTheDocument();
    });

    it("renders regression flags", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(
          screen.getByText("Month-over-Month Regressions"),
        ).toBeInTheDocument(),
      );
      expect(screen.getByText("tokens per issue")).toBeInTheDocument();
      expect(screen.getByText(/2026-05.*400\.0.*2026-06.*460\.0/)).toBeInTheDocument();
    });

    it("renders suggestions", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("Suggestions")).toBeInTheDocument(),
      );
      expect(screen.getByText("verbose skill")).toBeInTheDocument();
      expect(
        screen.getByText(/Skill 'implement' averages 9800/),
      ).toBeInTheDocument();
    });

    it("renders model outcomes table", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("Model vs. Outcome")).toBeInTheDocument(),
      );
      expect(screen.getByText("claude-sonnet-4-6")).toBeInTheDocument();
      expect(screen.getByText("92%")).toBeInTheDocument();
    });

    it("renders retry clustering section", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByText("Retry Clustering")).toBeInTheDocument(),
      );
      expect(screen.getByText("5")).toBeInTheDocument();
    });

    it("shows empty state when total_sessions is zero", async () => {
      setupMocks(EMPTY_REPORT);
      render(<ReportsPage />);
      await waitFor(() =>
        expect(
          screen.getByText(/No data available for this scope/),
        ).toBeInTheDocument(),
      );
      expect(
        screen.getByRole("button", { name: /refresh/i }),
      ).toBeInTheDocument();
    });

    it("shows error state on fetch failure", async () => {
      setupMocks("error");
      render(<ReportsPage />);
      await waitFor(() =>
        expect(screen.getByRole("alert")).toBeInTheDocument(),
      );
      expect(screen.getByText("Failed to load report")).toBeInTheDocument();
    });

    it("retries on error when Try again clicked", async () => {
      let reportCallCount = 0;
      mockGet.mockImplementation((url: string) => {
        if (url === "/runs/waves") return Promise.resolve(WAVES_RESPONSE);
        if (url.startsWith("/reports")) {
          reportCallCount++;
          if (reportCallCount === 1)
            return Promise.reject(new Error("network error"));
          return Promise.resolve(REPORT);
        }
        return Promise.reject(new Error("Unknown URL"));
      });

      render(<ReportsPage />);
      await waitFor(() => screen.getByRole("alert"));

      fireEvent.click(screen.getByRole("button", { name: /try again/i }));

      await waitFor(() =>
        expect(screen.getByText("42")).toBeInTheDocument(),
      );
    });
  });

  describe("By Wave scope", () => {
    it("shows wave selector when By Wave tab is clicked", async () => {
      setupMocks();
      render(<ReportsPage />);
      // Wait for mount effects to settle
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Wave" }));
      expect(
        screen.getByRole("combobox", { name: "Select wave" }),
      ).toBeInTheDocument();
    });

    it("shows idle prompt before wave is selected", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Wave" }));
      expect(
        screen.getByText(/Select a wave above to load its report/),
      ).toBeInTheDocument();
    });

    it("fetches wave report when a wave is selected", async () => {
      setupMocks(WAVE_REPORT);
      render(<ReportsPage />);
      // Wait for initial all-data load to complete
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Wave" }));
      const select = screen.getByRole("combobox", { name: "Select wave" });
      fireEvent.change(select, { target: { value: "Observability + UI" } });

      await waitFor(() =>
        expect(
          mockGet,
        ).toHaveBeenCalledWith(
          "/reports/wave/Observability%20%2B%20UI",
          expect.anything(),
        ),
      );
    });

    it("renders wave report content after selection", async () => {
      setupMocks(WAVE_REPORT);
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Wave" }));
      const select = screen.getByRole("combobox", { name: "Select wave" });
      fireEvent.change(select, { target: { value: "Observability + UI" } });

      await waitFor(() =>
        expect(screen.getAllByText("42").length).toBeGreaterThan(0),
      );
      expect(screen.getByText(/wave:Observability \+ UI/)).toBeInTheDocument();
    });
  });

  describe("By Month scope", () => {
    it("shows month input when By Month tab is clicked", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Month" }));
      expect(
        screen.getByLabelText("Select month"),
      ).toBeInTheDocument();
    });

    it("shows idle prompt before month is selected", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Month" }));
      expect(
        screen.getByText(/Select a month above to load its report/),
      ).toBeInTheDocument();
    });

    it("fetches month report when a valid month is entered", async () => {
      setupMocks(MONTH_REPORT);
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Month" }));
      const input = screen.getByLabelText("Select month");
      fireEvent.change(input, { target: { value: "2026-06" } });

      await waitFor(() =>
        expect(mockGet).toHaveBeenCalledWith(
          "/reports/month/2026-06",
          expect.anything(),
        ),
      );
    });

    it("renders month report content after valid month entry", async () => {
      setupMocks(MONTH_REPORT);
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Month" }));
      const input = screen.getByLabelText("Select month");
      fireEvent.change(input, { target: { value: "2026-06" } });

      await waitFor(() =>
        expect(screen.getByText(/month:2026-06/)).toBeInTheDocument(),
      );
    });

    it("does not fetch when month value is incomplete", async () => {
      setupMocks();
      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
      const callsBefore = mockGet.mock.calls.length;

      fireEvent.click(screen.getByRole("tab", { name: "By Month" }));
      const input = screen.getByLabelText("Select month");
      fireEvent.change(input, { target: { value: "2026" } });

      // No additional /reports call — just waves + initial all report
      expect(mockGet.mock.calls.length).toBe(callsBefore);
    });
  });

  describe("Empty state action", () => {
    it("shows View all data button for wave empty state", async () => {
      mockGet.mockImplementation((url: string) => {
        if (url === "/runs/waves") return Promise.resolve(WAVES_RESPONSE);
        if (url === "/reports") return Promise.resolve(REPORT);
        return Promise.resolve(EMPTY_REPORT);
      });

      render(<ReportsPage />);
      await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());

      fireEvent.click(screen.getByRole("tab", { name: "By Wave" }));
      const select = screen.getByRole("combobox", { name: "Select wave" });
      fireEvent.change(select, { target: { value: "Foundations" } });

      await waitFor(() =>
        expect(
          screen.getByText(/No data available for this scope/),
        ).toBeInTheDocument(),
      );
      expect(
        screen.getByRole("button", { name: /view all data/i }),
      ).toBeInTheDocument();
    });
  });
});
