import type { ReactNode } from "react";
import { cn } from "../cn";

/** Structural skeleton for loading states (baseline-ui: SHOULD use structural skeletons). */
export function LoadingState({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse space-y-3 p-4", className)}
      aria-busy="true"
      aria-label="Loading"
    >
      <div className="h-4 w-3/4 rounded bg-gray-200" />
      <div className="h-4 w-1/2 rounded bg-gray-200" />
      <div className="h-4 w-2/3 rounded bg-gray-200" />
    </div>
  );
}

/**
 * Empty state with one required next action (baseline-ui: MUST give empty states one clear
 * next action).
 */
export function EmptyState({
  message,
  action,
  className,
}: {
  message: string;
  action?: ReactNode;
  className?: string;
}) {
  if (import.meta.env.DEV && action === undefined) {
    console.warn(
      "[EmptyState] No action provided — baseline-ui MUST: give empty states one clear next action.",
    );
  }
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-4 p-8 text-center text-gray-500",
        className,
      )}
    >
      <p className="text-pretty">{message}</p>
      {action}
    </div>
  );
}

/** Error state rendered next to the action that produced it. */
export function ErrorState({
  message,
  retry,
  className,
}: {
  message: string;
  retry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn("rounded border border-red-200 bg-red-50 p-4", className)}
      role="alert"
    >
      <p className="text-pretty text-red-700">{message}</p>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="mt-2 text-sm font-medium text-red-600 underline hover:text-red-800"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** Wrapper for a successfully populated data view. */
export function PopulatedState({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn(className)}>{children}</div>;
}
