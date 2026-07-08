import { cn } from "@/lib/utils";

/**
 * Middle tier between bare page text and Card: a light, non-shadowed
 * surface for content that groups multiple pieces of info/controls but
 * isn't a repeating or independently-clickable unit (meta bars, filter
 * rows, step headers). Exported as a className string too, so a <Link>
 * standing in for this (e.g. a clickable banner row) can apply the same
 * look without being forced into a nested <div> — same reasoning as
 * button-variants.ts.
 */
export const rowClassName = "rounded-lg border border-[var(--border)] bg-[var(--muted)] p-[var(--space-surface-compact)]";

/** Plain function, no "use client", so Server Component pages can render it directly — same pattern as Card. */
export function Row({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn(rowClassName, className)} {...props} />;
}
