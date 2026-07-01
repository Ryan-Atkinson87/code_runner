import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfilePage } from "./ProfilePage";

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
const mockPost = apiClient.post as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RAW_YAML = `---
provider:
  default: claude
  plan: pro
  models:
    planning: claude-opus-4-8
    implementing: claude-sonnet-4-6
    reviewing: claude-sonnet-4-6
`;

const PROPOSE_OK = { outcome: "proposed", raw_yaml: RAW_YAML, error: "" };
const PROPOSE_ERROR = { outcome: "error", raw_yaml: "", error: "Claude session failed to produce a valid profile" };
const CONFIRM_OK = { written: true, path: "execution-profile.yaml" };
const REJECT_OK = { written: false, path: "" };

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

describe("ProfilePage", () => {
  it("shows idle state on mount with Generate button", () => {
    render(<ProfilePage />);
    expect(screen.getByRole("button", { name: "Generate profile" })).toBeInTheDocument();
    expect(screen.getByText(/execution-profile\.yaml/)).toBeInTheDocument();
  });

  it("shows generating state while POST /profile/propose is in-flight", async () => {
    mockPost.mockReturnValue(new Promise(() => {}));
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/Generating execution profile/),
    );
  });

  it("calls POST /profile/propose when generate is clicked", async () => {
    mockPost.mockResolvedValueOnce(PROPOSE_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith("/profile/propose"));
  });

  it("shows proposed YAML for review after successful propose", async () => {
    mockPost.mockResolvedValueOnce(PROPOSE_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() =>
      expect(screen.getByLabelText("Proposed execution-profile.yaml content")).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Proposed execution-profile.yaml content")).toHaveTextContent(
      "claude-opus-4-8",
    );
  });

  it("shows Confirm & write and Reject buttons after proposal", async () => {
    mockPost.mockResolvedValueOnce(PROPOSE_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Confirm & write" }));
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("shows error state when propose returns outcome=error", async () => {
    mockPost.mockResolvedValueOnce(PROPOSE_ERROR);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Claude session failed");
  });

  it("shows error state on network failure", async () => {
    mockPost.mockRejectedValueOnce(new Error("timeout"));
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to generate profile");
  });

  it("error state shows Try again button that resets to idle", async () => {
    mockPost.mockRejectedValueOnce(new Error("timeout"));
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Try again" }));
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Try again" })); });
    expect(screen.getByRole("button", { name: "Generate profile" })).toBeInTheDocument();
  });

  it("confirms before writing profile", async () => {
    mockPost
      .mockResolvedValueOnce(PROPOSE_OK)
      .mockResolvedValueOnce(CONFIRM_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Confirm & write" }));

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Confirm & write" })); });

    expect(window.confirm).toHaveBeenCalledWith(
      "Write this profile to execution-profile.yaml? This cannot be undone from the UI.",
    );
  });

  it("calls POST /profile/confirm and shows success state", async () => {
    mockPost
      .mockResolvedValueOnce(PROPOSE_OK)
      .mockResolvedValueOnce(CONFIRM_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Confirm & write" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Confirm & write" })); });

    expect(mockPost).toHaveBeenLastCalledWith("/profile/confirm");
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Profile written to execution-profile.yaml");
  });

  it("does not call confirm API when user cancels the confirm dialog", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => false);
    mockPost.mockResolvedValueOnce(PROPOSE_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Confirm & write" }));
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Confirm & write" })); });
    expect(mockPost).toHaveBeenCalledTimes(1); // only propose, not confirm
  });

  it("calls POST /profile/reject and shows rejected state on reject confirm", async () => {
    mockPost
      .mockResolvedValueOnce(PROPOSE_OK)
      .mockResolvedValueOnce(REJECT_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Reject" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reject" })); });

    expect(mockPost).toHaveBeenLastCalledWith("/profile/reject");
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Proposal discarded. Nothing was written.");
  });

  it("does not call reject API when user cancels the reject dialog", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => false);
    mockPost.mockResolvedValueOnce(PROPOSE_OK);
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Reject" }));
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Reject" })); });
    expect(mockPost).toHaveBeenCalledTimes(1); // only propose, not reject
  });

  it("shows confirm error inline on /profile/confirm failure", async () => {
    mockPost
      .mockResolvedValueOnce(PROPOSE_OK)
      .mockRejectedValueOnce(new ApiError(409, "No pending proposal"));
    render(<ProfilePage />);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "Generate profile" })); });
    await waitFor(() => screen.getByRole("button", { name: "Confirm & write" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Confirm & write" })); });

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("No pending proposal");
    // Should still show Confirm & write so user can retry
    expect(screen.getByRole("button", { name: "Confirm & write" })).toBeInTheDocument();
  });
});
