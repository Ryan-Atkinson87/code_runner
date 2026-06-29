import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { cn } from "../cn";

const NAV_ITEMS = [
  { to: "/runs", label: "Runs" },
  { to: "/progress", label: "Progress" },
  { to: "/usage", label: "Usage" },
  { to: "/blockers", label: "Blockers" },
  { to: "/prs", label: "PRs" },
  { to: "/reports", label: "Reports" },
  { to: "/settings", label: "Settings" },
  { to: "/profile", label: "Profile" },
] as const;

export function Layout() {
  const { logout } = useAuth();

  return (
    <div className="flex h-dvh">
      <nav
        className="flex w-48 flex-shrink-0 flex-col bg-gray-900 text-white"
        aria-label="Main navigation"
      >
        <div className="px-4 py-3 text-xs font-semibold uppercase text-gray-400">
          Code Runner
        </div>
        <ul className="flex-1 space-y-0.5 px-2 py-2" role="list">
          {NAV_ITEMS.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    "block rounded px-3 py-2 text-sm",
                    isActive
                      ? "bg-gray-700 text-white"
                      : "text-gray-300 hover:bg-gray-800 hover:text-white",
                  )
                }
              >
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="px-2 py-3">
          <button
            type="button"
            onClick={() => void logout()}
            className="w-full rounded px-3 py-2 text-left text-sm text-gray-400 hover:bg-gray-800 hover:text-white"
          >
            Log out
          </button>
        </div>
      </nav>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
