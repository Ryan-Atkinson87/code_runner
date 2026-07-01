import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UsageGaugesPage } from "./UsageGaugesPage";

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
    },
  };
});

const { apiClient } = await import("../api");
const mockGet = apiClient.get as ReturnType<typeof vi.fn>;
const mockPost = apiClient.post as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SNAPSHOT = {
  meters: [
    {
      kind: "token_daily",
      utilisation: 0.62,
      resets_at: 1750060800.0,
      limit: 1000000,
      used: 620000,
      is_governing: true,
    },
    {
      kind: "token_monthly",
      utilisation: 0.3,
      resets_at: null,
      limit: null,
      used: null,
      is_governing: false,
    },
  ],
  threshold_percent: 80,
  threshold_reached: false,
  override_active: false,
  provider: "claude",
  plan: "pro",
};

const SNAPSHOT_THRESHOLD_REACHED = {
  ...SNAPSHOT,
  meters: [
    { ...SNAPSHOT.meters[0], utilisation: 0.92 },
    SNAPSHOT.meters[1],
  ],
  threshold_reached: true,
};

const SNAPSHOT_EMPTY_METERS = { ...SNAPSHOT, meters: [] };

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockImplementation(() => true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("UsageGaugesPage", () => {
  it("shows loading state while fetching", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<UsageGaugesPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows empty state when meters array is empty", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT_EMPTY_METERS);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByText(/No usage meters available/)).toBeInTheDocument(),
    );
  });

  it("shows error state when fetch fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("timeout"));
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to load usage data")).toBeInTheDocument();
  });

  it("renders all meters from the snapshot", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByText("Token Daily")).toBeInTheDocument(),
    );
    expect(screen.getByText("Token Monthly")).toBeInTheDocument();
  });

  it("highlights the governing meter with badge and border style", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByText("Governing")).toBeInTheDocument(),
    );
    const governingArticle = screen.getByRole("article", {
      name: /Token Daily meter \(governing\)/,
    });
    expect(governingArticle.className).toContain("border-indigo-400");
  });

  it("renders meter bar with correct aria attributes", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getAllByRole("meter")).toHaveLength(2),
    );
    const governingMeter = screen.getByRole("meter", {
      name: "Token Daily usage",
    });
    expect(governingMeter).toHaveAttribute("aria-valuenow", "62");
    expect(governingMeter).toHaveAttribute("aria-valuemin", "0");
    expect(governingMeter).toHaveAttribute("aria-valuemax", "100");
  });

  it("shows threshold reached alert when threshold_reached is true", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT_THRESHOLD_REACHED);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Threshold reached"),
    );
  });

  it("shows 80% threshold text label on each gauge", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getAllByText(/80% threshold/).length).toBeGreaterThan(0),
    );
  });

  it("renders override switch reflecting current state (inactive)", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Usage override" })).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("switch", { name: "Usage override" }),
    ).toHaveAttribute("aria-checked", "false");
  });

  it("confirms before toggling override", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() => screen.getByRole("switch"));

    act(() => {
      fireEvent.click(screen.getByRole("switch", { name: "Usage override" }));
    });

    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("calls POST /usage/override with correct body on confirm", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    mockPost.mockResolvedValueOnce({ override_active: true });
    render(<UsageGaugesPage />);
    await waitFor(() => screen.getByRole("switch"));

    act(() => {
      fireEvent.click(screen.getByRole("switch", { name: "Usage override" }));
    });

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/usage/override", { active: true }),
    );
  });

  it("reflects updated override state after successful toggle", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    mockPost.mockResolvedValueOnce({ override_active: true });
    render(<UsageGaugesPage />);
    await waitFor(() => screen.getByRole("switch"));

    act(() => {
      fireEvent.click(screen.getByRole("switch", { name: "Usage override" }));
    });

    await waitFor(() =>
      expect(
        screen.getByRole("switch", { name: "Usage override" }),
      ).toHaveAttribute("aria-checked", "true"),
    );
    expect(
      screen.getByText(/Override active/),
    ).toBeInTheDocument();
  });

  it("shows provider and plan in header", async () => {
    mockGet.mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() =>
      expect(screen.getByText(/claude/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/pro plan/)).toBeInTheDocument();
  });

  it("polls GET /usage/gauges at 30-second intervals", async () => {
    // Capture the interval callback without fake timers
    let pollCallback: (() => void) | null = null;
    vi.spyOn(globalThis, "setInterval").mockImplementation(
      (cb: TimerHandler, ms?: number) => {
        if (ms === 30_000) {
          pollCallback = cb as () => void;
          return 1 as unknown as ReturnType<typeof setInterval>;
        }
        return 0 as unknown as ReturnType<typeof setInterval>;
      },
    );

    mockGet.mockResolvedValue(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    // Simulate interval firing
    act(() => { pollCallback?.(); });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it("shows retry button on error that refetches on click", async () => {
    mockGet
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(SNAPSHOT);
    render(<UsageGaugesPage />);
    await waitFor(() => screen.getByRole("alert"));

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    await waitFor(() =>
      expect(screen.getByText("Token Daily")).toBeInTheDocument(),
    );
  });
});
