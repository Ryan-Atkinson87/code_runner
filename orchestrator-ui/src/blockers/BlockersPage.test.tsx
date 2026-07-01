import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BlockersPage } from "./BlockersPage";

// ---------------------------------------------------------------------------
// Module mock
// ---------------------------------------------------------------------------

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    ApiError: mod.ApiError,
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

const apiMod = await import("../api");
const mockGet = apiMod.apiClient.get as ReturnType<typeof vi.fn>;
const mockPost = apiMod.apiClient.post as ReturnType<typeof vi.fn>;
const { ApiError } = apiMod;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BLOCKER: typeof import("../api") extends never ? never : object = {
  id: 1,
  run_id: 7,
  issue_number: 42,
  blocker_type: "missing_spec",
  reason: "Spec §12 does not cover the PRs empty state.",
  needed_to_unblock: "Confirm whether to show a GitHub link or just a message.",
  status: "parked",
  created_at: "2026-06-29T10:00:00Z",
  resolved_at: null,
  resolution_response: null,
};

const BLOCKERS_RESPONSE = { blockers: [BLOCKER], run_id: 7 };
const EMPTY_RESPONSE = { blockers: [], run_id: 7 };

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

describe("BlockersPage", () => {
  it("shows loading state on mount", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<BlockersPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows healthy empty state when no blockers", async () => {
    mockGet.mockResolvedValueOnce(EMPTY_RESPONSE);
    render(<BlockersPage />);
    await waitFor(() =>
      expect(screen.getByText(/run is healthy/)).toBeInTheDocument(),
    );
  });

  it("shows no-active-run empty state on 404", async () => {
    mockGet.mockRejectedValueOnce(new ApiError(404, "Not Found"));
    render(<BlockersPage />);
    await waitFor(() =>
      expect(screen.getByText(/No active run/)).toBeInTheDocument(),
    );
  });

  it("shows error state on fetch failure", async () => {
    mockGet.mockRejectedValueOnce(new Error("timeout"));
    render(<BlockersPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to load blockers")).toBeInTheDocument();
  });

  it("renders blocker list from the API", async () => {
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    render(<BlockersPage />);
    await waitFor(() =>
      expect(screen.getByText("Missing Spec")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("Spec §12 does not cover the PRs empty state."),
    ).toBeInTheDocument();
    expect(screen.getByText(/issue #42/i)).toBeInTheDocument();
  });

  it("renders inline response form for parked blocker", async () => {
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));
    expect(screen.getByRole("button", { name: "Send response" })).toBeDisabled();
  });

  it("enables submit button when text is entered", async () => {
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "Show a message only." },
      });
    });

    expect(screen.getByRole("button", { name: "Send response" })).not.toBeDisabled();
  });

  it("posts to the correct endpoint on submit", async () => {
    const resolved = { ...BLOCKER, status: "resolved", resolution_response: "Show a message." };
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    mockPost.mockResolvedValueOnce(resolved);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "Show a message." },
      });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send response" }));
    });

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/blockers/42/resolve", {
        response: "Show a message.",
      }),
    );
  });

  it("shows resolved state after successful submit", async () => {
    const resolved = { ...BLOCKER, status: "resolved", resolution_response: "Show a message." };
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    mockPost.mockResolvedValueOnce(resolved);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "Show a message." },
      });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send response" }));
    });

    await waitFor(() =>
      expect(screen.getByText("Resolved")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Response:/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send response" })).not.toBeInTheDocument();
  });

  it("shows inline error when POST fails", async () => {
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    mockPost.mockRejectedValueOnce(new Error("network failure"));
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "My answer." },
      });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send response" }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to send response")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send response" })).toBeInTheDocument();
  });

  it("shows retry button on error that refetches", async () => {
    mockGet
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(BLOCKERS_RESPONSE);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("alert"));

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    await waitFor(() =>
      expect(screen.getByText("Missing Spec")).toBeInTheDocument(),
    );
  });

  it("moves focus to the resolved section after successful submit", async () => {
    const resolved = { ...BLOCKER, status: "resolved", resolution_response: "Show a message." };
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    mockPost.mockResolvedValueOnce(resolved);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "Show a message." },
      });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send response" }));
    });

    await waitFor(() =>
      expect(
        screen.getByLabelText("Blocker resolved — your response has been submitted"),
      ).toHaveFocus(),
    );
  });

  it("resolved section has accessible label for screen reader announcement", async () => {
    const resolved = { ...BLOCKER, status: "resolved", resolution_response: "Show a message." };
    mockGet.mockResolvedValueOnce(BLOCKERS_RESPONSE);
    mockPost.mockResolvedValueOnce(resolved);
    render(<BlockersPage />);
    await waitFor(() => screen.getByRole("textbox", { name: "Your response" }));

    act(() => {
      fireEvent.change(screen.getByRole("textbox", { name: "Your response" }), {
        target: { value: "Show a message." },
      });
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Send response" }));
    });

    await waitFor(() =>
      expect(
        screen.getByLabelText("Blocker resolved — your response has been submitted"),
      ).toBeInTheDocument(),
    );
  });
});
