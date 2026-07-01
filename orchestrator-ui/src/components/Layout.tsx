import { useState } from "react";
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
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-dvh">
      {/* #186: Skip to content — first focusable element for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow"
      >
        Skip to content
      </a>

      {/* #189: Mobile overlay — closes sidebar on backdrop click */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          aria-hidden="true"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar — fixed drawer on mobile, static flex column on md+ */}
      <nav
        id="main-nav"
        aria-label="Main navigation"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-48 flex-shrink-0 flex-col bg-gray-900 text-white transition-transform duration-200",
          "md:relative md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        )}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-xs font-semibold uppercase text-gray-400">
            Code Runner
          </span>
          {/* Close button — mobile only */}
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation"
            className="rounded p-1 text-gray-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-white md:hidden"
          >
            <svg
              aria-hidden="true"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <ul className="flex-1 space-y-0.5 px-2 py-2" role="list">
          {NAV_ITEMS.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                onClick={() => setSidebarOpen(false)}
                className={({ isActive }) =>
                  cn(
                    /* #188: min-h-[44px] for touch-target compliance */
                    "flex min-h-[44px] items-center rounded px-3 py-2.5 text-sm",
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
          {/* #188: min-h-[44px] on logout button */}
          <button
            type="button"
            onClick={() => void logout()}
            className="flex min-h-[44px] w-full items-center rounded px-3 py-3 text-left text-sm text-gray-400 hover:bg-gray-800 hover:text-white"
          >
            Log out
          </button>
        </div>
      </nav>

      {/* Content area: mobile header + main */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* #189: Mobile header with hamburger — hidden on md+ */}
        <div className="flex items-center border-b border-gray-200 bg-white px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open navigation"
            aria-expanded={sidebarOpen}
            aria-controls="main-nav"
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded p-2 text-gray-500 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
          >
            <svg
              aria-hidden="true"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
          <span className="ml-3 text-sm font-semibold text-gray-700">Code Runner</span>
        </div>

        {/* #186: id="main-content" for skip link target */}
        <main id="main-content" className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
