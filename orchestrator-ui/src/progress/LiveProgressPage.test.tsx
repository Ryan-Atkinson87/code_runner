import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveProgressPage } from "./LiveProgressPage";

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock("../api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api")>();
  return {
    ...mod,
    API_BASE: "http://testserver/api",
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

const { apiClient } = await import("../api");
const mockGet = apiClient.get as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// FakeEventSource — supports named events via addEventListener
// ---------------------------------------------------------------------------

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((ev: MessageEvent<string>) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  close = vi.fn();

  private _listeners: Map<string, Set<(ev: Event) => void>> = new Map();

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: Event) => void) {
    if (!this._listeners.has(type)) this._listeners.set(type, new Set());
    this._listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (ev: Event) => void) {
    this._listeners.get(type)?.delete(listener);
  }

  /** Emit a named SSE event — call inside act() to flush React state updates. */
  emit(type: string, data: unknown) {
    const ev = new MessageEvent(type, { data: JSON.stringify(data) });
    this._listeners.get(type)?.forEach((l) => l(ev));
  }

  /** Simulate a connection error — call inside act() to flush React state updates. */
  emitError() {
    this.onerror?.(new Event("error"));
  }
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const ACTIVE_RUN_STATUS = { active: true, run: { run_id: 7 } };
const NO_RUN_STATUS = { active: false, run: null };

function getLatestFake(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1];
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LiveProgressPage", () => {
  it("shows loading state while fetching run status", () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<LiveProgressPage />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("shows empty state when no active run", async () => {
    mockGet.mockResolvedValueOnce(NO_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() =>
      expect(screen.getByText(/No active run/)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Go to Runs" })).toBeInTheDocument();
  });

  it("shows error state when fetch fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("network failure"));
    render(<LiveProgressPage />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to load run status")).toBeInTheDocument();
  });

  it("connects SSE to the correct URL when run is active", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(getLatestFake().url).toBe("http://testserver/api/runs/7/progress");
  });

  it("shows connecting state before first SSE event", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getByRole("status")).toHaveTextContent("Connecting…");
  });

  it("shows live status and run info after run_state event", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "running",
      });
    });

    expect(screen.getByRole("status")).toHaveTextContent("Live");
    expect(screen.getByText("Phase 6")).toBeInTheDocument();
    expect(screen.getByText("code_runner")).toBeInTheDocument();
  });

  it("adds run_state entry to the event log", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "running",
      });
    });

    expect(screen.getByText(/Status: running/)).toBeInTheDocument();
  });

  it("shows current issue and role on issue_started", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "running",
      });
      getLatestFake().emit("issue_started", {
        run_id: 7,
        issue_number: 42,
        role: "implementor",
      });
    });

    expect(screen.getByText("#42")).toBeInTheDocument();
    expect(screen.getByText("implementor")).toBeInTheDocument();
  });

  it("adds session_event tool_call entry to the log", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("session_event", {
        run_id: 7,
        issue_number: 42,
        role: "implementor",
        event: {
          kind: "tool_call",
          content: "",
          tool_name: "Edit",
          timestamp: 1750000000,
        },
      });
    });

    expect(screen.getByText(/\[tool_call\] Edit/)).toBeInTheDocument();
  });

  it("adds issue_completed entry and clears issue context", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "running",
      });
      getLatestFake().emit("issue_started", {
        run_id: 7,
        issue_number: 42,
        role: "implementor",
      });
      getLatestFake().emit("issue_completed", {
        run_id: 7,
        issue_number: 42,
        outcome: "completed",
      });
    });

    expect(screen.getByText("Issue #42 completed")).toBeInTheDocument();
    expect(screen.queryByText("#42")).not.toBeInTheDocument();
  });

  it("shows ended status on run_ended event", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "completed",
      });
      getLatestFake().emit("run_ended", {});
    });

    expect(screen.getByRole("status")).toHaveTextContent("Ended");
    expect(screen.getByText("Run ended")).toBeInTheDocument();
  });

  it("shows reconnecting status on SSE error", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      getLatestFake().emit("run_state", {
        run_id: 7,
        wave: "Phase 6",
        project: "code_runner",
        provider: "claude",
        status: "running",
      });
    });
    expect(screen.getByRole("status")).toHaveTextContent("Live");

    act(() => {
      getLatestFake().emitError();
    });

    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting…");
  });

  it("caps log at MAX_LOG entries without error", async () => {
    mockGet.mockResolvedValueOnce(ACTIVE_RUN_STATUS);
    render(<LiveProgressPage />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      for (let i = 0; i < 250; i++) {
        getLatestFake().emit("session_event", {
          run_id: 7,
          issue_number: 1,
          role: "implementor",
          event: { kind: "output", content: `line ${i}`, timestamp: i },
        });
      }
    });

    expect(screen.getByText(/showing last 200/)).toBeInTheDocument();
  });
});
