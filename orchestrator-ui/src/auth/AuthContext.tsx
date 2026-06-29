import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import { API_BASE } from "../api";

type AuthState = "checking" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  state: AuthState;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>("checking");

  useEffect(() => {
    fetch(`${API_BASE}/session`, { credentials: "include" })
      .then((res) => setState(res.ok ? "authenticated" : "unauthenticated"))
      .catch(() => setState("unauthenticated"));
  }, []);

  const login = useCallback(async (password: string) => {
    const res = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
      credentials: "include",
    });
    if (!res.ok) {
      let detail = "Login failed";
      try {
        const data = (await res.json()) as { detail?: string };
        if (data.detail) detail = data.detail;
      } catch {
        // ignore parse error, use default message
      }
      throw new Error(detail);
    }
    setState("authenticated");
  }, []);

  const logout = useCallback(async () => {
    await fetch(`${API_BASE}/logout`, { method: "POST", credentials: "include" });
    setState("unauthenticated");
  }, []);

  return (
    <AuthContext.Provider value={{ state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
