import { Outlet, createBrowserRouter } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { RunControlPage } from "./runs/RunControlPage";

export const router = createBrowserRouter([
  {
    // AuthProvider wraps all routes so auth state is available everywhere.
    element: (
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    ),
    children: [
      {
        path: "/login",
        element: <LoginPage />,
      },
      {
        path: "/",
        element: (
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        ),
        children: [
          // Feature screens #61–#68 will nest here; each issue adds its own route.
          {
            index: true,
            element: (
              <p className="p-6 text-gray-500">Select a section from the navigation.</p>
            ),
          },
          { path: "runs", element: <RunControlPage /> },
        ],
      },
    ],
  },
]);
