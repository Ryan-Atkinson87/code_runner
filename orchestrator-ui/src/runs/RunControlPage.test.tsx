import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RunControlPage } from "./RunControlPage";

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

const OPEN_WAVES = [
  { name: "phase-1", milestone_number: 1, state: "open" as const },
  { name: "phase-2", milestone_number: 2, state: "open" as const },
];

const CLOSED_WAVES = [
  { name: "phase-0", milestone_number: 0, state: "closed" as const },
];

const NO_RUN = { active: false, run: null };

const ACTIVE_RUN = {
  active: true,
  run: {
    run_id: 42,
    project: "my-project",
    wave: "phase-1",
    provider: "claude",
    status: "running" as const,
  },
};

const PAUSED_RUN = {
  active: true,
  run: { ...ACTIVE_RUN.run, status: "paused" as const },
};

const DEFAULT_PROVIDERS = { providers: ["claude", "codex", "gemini"] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("RunControlPage", () => {
  it("shows loading skeleton while fetching", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<RunControlPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows error state when API fails", async () => {
    mockGet.mockRejectedValue(new Error("Network error"));
    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByText("Failed to load run data")).toBeInTheDocument(),
    );
  });

  it("shows start form with only open waves", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: [...OPEN_WAVES, ...CLOSED_WAVES] })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Wave")).toBeInTheDocument(),
    );
    const opts = screen.getAllByRole("option").map((o) => o.textContent);
    expect(opts).toContain("phase-1");
    expect(opts).toContain("phase-2");
    expect(opts).not.toContain("phase-0");
  });

  it("shows empty state when no open waves exist", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: CLOSED_WAVES })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS)
      .mockResolvedValueOnce({});
    render(<RunControlPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/No open waves available/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("shows GitHub milestones link in empty state when config provides github_url", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: CLOSED_WAVES })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS)
      .mockResolvedValueOnce({ github_url: "https://github.com/owner/repo" });
    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /Open GitHub milestones/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /Open GitHub milestones/i })).toHaveAttribute(
      "href",
      "https://github.com/owner/repo/milestones",
    );
  });

  it("shows no action link in empty state when config has no github_url", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: CLOSED_WAVES })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS)
      .mockResolvedValueOnce({});
    render(<RunControlPage />);
    await waitFor(() => screen.getByText(/No open waves available/));
    expect(screen.queryByRole("link", { name: /milestones/i })).not.toBeInTheDocument();
  });

  it("shows dynamically loaded providers in the provider select", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce({ providers: ["claude", "codex", "gemini", "gpt4"] });
    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Provider")).toBeInTheDocument(),
    );
    const select = screen.getByLabelText("Provider");
    expect(select).toHaveTextContent("claude");
    expect(select).toHaveTextContent("codex");
    expect(select).toHaveTextContent("gemini");
    expect(select).toHaveTextContent("gpt4");
  });

  it("calls POST /runs/start with selected wave and provider", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(NO_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    mockPost.mockResolvedValueOnce(ACTIVE_RUN.run);

    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Wave")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("Wave"), {
      target: { value: "phase-1" },
    });
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "codex" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/runs/start", {
        wave: "phase-1",
        provider: "codex",
      }),
    );
  });

  it("shows active run panel when a run is running", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(ACTIVE_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByText("Active Run")).toBeInTheDocument(),
    );
    expect(screen.getByText("my-project")).toBeInTheDocument();
    expect(screen.getByText("phase-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("requires confirm before pausing", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(ACTIVE_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    mockPost.mockResolvedValueOnce(PAUSED_RUN.run);

    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith("/runs/42/pause"));
  });

  it("requires confirm before stopping", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(ACTIVE_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    mockPost.mockResolvedValueOnce({ ...ACTIVE_RUN.run, status: "stopped" });

    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith("/runs/42/stop"));
  });

  it("resumes without confirm dialog", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(PAUSED_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    mockPost.mockResolvedValueOnce(ACTIVE_RUN.run);

    render(<RunControlPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Resume" }),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(window.confirm).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/runs/42/resume"),
    );
  });

  it("shows inline action error on API failure", async () => {
    mockGet
      .mockResolvedValueOnce({ waves: OPEN_WAVES })
      .mockResolvedValueOnce(ACTIVE_RUN)
      .mockResolvedValueOnce(DEFAULT_PROVIDERS);
    mockPost.mockRejectedValueOnce(new Error("Server error"));

    render(<RunControlPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Failed to stop run"),
    );
  });
});
