import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const passwordId = useId();
  const errorId = `${passwordId}-error`;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const password = fd.get("password") as string;

    setPending(true);
    setError(null);
    try {
      await login(password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex h-dvh items-center justify-center bg-gray-50 px-4 sm:px-0">
      <div className="w-full max-w-sm rounded-lg bg-white p-8 shadow">
        <h1 className="mb-6 text-balance text-xl font-semibold text-gray-900">Code Runner</h1>
        <form onSubmit={(e) => void handleSubmit(e)} noValidate>
          <div className="mb-4">
            <label
              htmlFor={passwordId}
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Password
            </label>
            <input
              id={passwordId}
              name="password"
              type="password"
              required
              autoComplete="current-password"
              aria-required="true"
              aria-describedby={error ? errorId : undefined}
              className="w-full rounded border border-gray-300 px-3 py-3 text-base focus:outline-none focus:ring-2 focus:ring-gray-900 sm:py-2 sm:text-sm"
            />
          </div>
          {error && (
            <p
              id={errorId}
              role="alert"
              className="mb-4 text-pretty text-sm text-red-600"
            >
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded bg-gray-900 px-4 py-3 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {pending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
