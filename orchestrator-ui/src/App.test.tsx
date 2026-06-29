import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { App } from "./App";

// Stub AuthProvider so no fetch is made and auth state stays "checking",
// preventing react-router navigation that triggers an AbortSignal compat issue
// between jsdom and Node's built-in fetch (undici).
vi.mock("./auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({ state: "checking" as const, login: vi.fn(), logout: vi.fn() }),
}));

describe("App", () => {
  it("renders the loading skeleton while auth state is checking", () => {
    render(<App />);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });
});
