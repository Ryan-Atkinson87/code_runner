import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./ProtectedRoute";

vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

function renderRoute(state: "checking" | "authenticated" | "unauthenticated") {
  vi.mocked(useAuth).mockReturnValue({
    state,
    login: vi.fn(),
    logout: vi.fn(),
  });

  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <div>Protected content</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("shows loading skeleton when auth state is checking", () => {
    renderRoute("checking");
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
  });

  it("renders children when authenticated", () => {
    renderRoute("authenticated");
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("redirects to /login when unauthenticated", () => {
    renderRoute("unauthenticated");
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).toBeNull();
  });
});
