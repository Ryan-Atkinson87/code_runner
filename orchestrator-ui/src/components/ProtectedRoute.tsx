import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { LoadingState } from "./StateViews";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { state } = useAuth();

  if (state === "checking") return <LoadingState />;
  if (state === "unauthenticated") return <Navigate to="/login" replace />;
  return <>{children}</>;
}
