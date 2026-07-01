import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PrsPage } from "./PrsPage";

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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PR = {
  number: 42,
  title: "#12 Add project.yaml loader",
  body: "## Summary\nAdds the config loader.\n\n## Test plan\n- [ ] Review the config schema\n- [x] Tests pass",
  html_url: "https://github.com/Ryan-Atkinson87/code_runner/pull/42",
  head_branch: "issue-12-config-loader",
  base_branch: "main",
  state: "open",
  checklist: [
    { text: "Review the config schema", checked: false },
    { text: "Tests pass", checked: true },
  ],
};

const PRS_RESPONSE = { prs: [PR] };
const EMPTY_RESPONSE = { prs: [] };

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

describe("PrsPage", () => {
  it("shows loading state on mount", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<PrsPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows empty state when no PRs", async () => {
    mockGet.mockResolvedValueOnce(EMPTY_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText(/No hand-off PRs/)).toBeInTheDocument(),
    );
  });

  it("shows error state on fetch failure", async () => {
    mockGet.mockRejectedValueOnce(new Error("timeout"));
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to load pull requests")).toBeInTheDocument();
  });

  it("renders PR title and number", async () => {
    mockGet.mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText(/#12 Add project\.yaml loader/)).toBeInTheDocument(),
    );
  });

  it("renders PR body text", async () => {
    mockGet.mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText(/Adds the config loader/)).toBeInTheDocument(),
    );
  });

  it("renders checklist items with checked/unchecked state", async () => {
    mockGet.mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText("Review the config schema")).toBeInTheDocument(),
    );
    expect(screen.getByText("Tests pass")).toBeInTheDocument();
    // Unchecked item
    expect(
      screen.getByLabelText("Unchecked: Review the config schema"),
    ).toBeInTheDocument();
    // Checked item
    expect(
      screen.getByLabelText("Checked: Tests pass"),
    ).toBeInTheDocument();
  });

  it("links to GitHub PR", async () => {
    mockGet.mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: /Open pull request #42 on GitHub/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: /Open pull request #42 on GitHub/i }),
    ).toHaveAttribute("href", PR.html_url);
  });

  it("shows 'Ready to merge' badge when all checklist items checked", async () => {
    const allChecked = {
      ...PR,
      checklist: [
        { text: "Review the config schema", checked: true },
        { text: "Tests pass", checked: true },
      ],
    };
    mockGet.mockResolvedValueOnce({ prs: [allChecked] });
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText("Ready to merge")).toBeInTheDocument(),
    );
  });

  it("shows retry button on error that refetches", async () => {
    mockGet
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() => screen.getByRole("alert"));

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    });

    await waitFor(() =>
      expect(screen.getByText(/#12 Add project\.yaml loader/)).toBeInTheDocument(),
    );
  });

  it("renders checklist progress count", async () => {
    mockGet.mockResolvedValueOnce(PRS_RESPONSE);
    render(<PrsPage />);
    await waitFor(() =>
      expect(screen.getByText("1/2 checked")).toBeInTheDocument(),
    );
  });
});
