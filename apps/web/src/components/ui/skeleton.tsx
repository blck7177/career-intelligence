import { cn } from "@/lib/utils";

/**
 * Pulsing placeholder block for content that's still loading. Plain
 * function, no "use client" — the pulse is pure CSS (globals.css'
 * .animate-skeleton-pulse), so this is safe to render from Server
 * Components too.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("rounded-md bg-[var(--muted)] animate-skeleton-pulse", className)} />;
}
