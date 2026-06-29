import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "./LoginPage";

const mockLogin = vi.fn();
const mockLogout = vi.fn();

vi.mock("./AuthContext", () => ({
  useAuth: () => ({
    state: "unauthenticated",
    login: mockLogin,
    logout: mockLogout,
  }),
}));

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>Home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockLogout.mockReset();
  });

  it("renders a password field and submit button", () => {
    renderLoginPage();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("password field has type=password", () => {
    renderLoginPage();
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("type", "password");
  });

  it("calls login with the entered password on submit", async () => {
    mockLogin.mockResolvedValue(undefined);
    renderLoginPage();

    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith("secret"));
  });

  it("shows error message on failed login", async () => {
    mockLogin.mockRejectedValue(new Error("Unauthorized"));
    renderLoginPage();

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Unauthorized"));
  });

  it("error is linked to input via aria-describedby", async () => {
    mockLogin.mockRejectedValue(new Error("Bad password"));
    renderLoginPage();

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => screen.getByRole("alert"));

    const input = screen.getByLabelText(/password/i);
    const errorId = input.getAttribute("aria-describedby");
    expect(errorId).toBeTruthy();
    expect(document.getElementById(errorId!)).toBeInTheDocument();
  });

  it("disables submit while pending", async () => {
    let resolveLogin!: () => void;
    mockLogin.mockImplementation(
      () =>
        new Promise<void>((res) => {
          resolveLogin = res;
        }),
    );
    renderLoginPage();

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();

    resolveLogin();
    await waitFor(() => expect(screen.queryByRole("button", { name: /signing in/i })).toBeNull());
  });

  it("navigates to / after successful login", async () => {
    mockLogin.mockResolvedValue(undefined);
    renderLoginPage();

    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByText("Home")).toBeInTheDocument());
  });
});
