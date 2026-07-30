import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  /** Second line under the title. Use for a sentence; a bare count/date belongs in `meta`. */
  subtitle?: string;
  /** Right-aligned, baseline-shared 11px stamp — counts, dates, "Week N of search". */
  meta?: ReactNode;
  /** Right-aligned control(s). Pushes the row to top-alignment so a 36px button doesn't ride the baseline. */
  actions?: ReactNode;
  /**
   * "edge"  — 56px (--space-row-edge) side padding, for full-bleed views (tracker).
   * "page"  — 28px (--space-page-x), for a full-bleed view that wants the page gutter.
   * "none"  — no padding: the header is rendered INSIDE a PageContainer and
   *           inherits its 28px gutter, so title and body share one left edge.
   */
  gutter?: "edge" | "page" | "none";
  className?: string;
}

/**
 * The app's single page-identity block: a 17px/600 title with optional
 * subtitle, right-aligned meta and right-aligned actions.
 *
 * Promoted out of app/[locale]/tracker/PageHeader.tsx, which is now a thin
 * client wrapper that keeps the planner-settings fetch (that effect is
 * load-bearing — it avoids an SSR hydration mismatch on a client-local date)
 * and passes the result down as `meta`. Everything data-shaped reaches this
 * component as an already-rendered node, which is why this stays a plain
 * function with no "use client": /runs is a Server Component and renders it
 * directly, same rule as card.tsx and page-container.tsx.
 *
 * It replaces three divergent page titles: 22px font-bold (workspace), 20px
 * (profile — a size that isn't even on the type ladder) and 22px semibold
 * (/runs). Detail pages use DetailBackBar instead, which carries the same
 * title/meta/right shape at the 56px bar height.
 */
export function PageHeader({
  title,
  subtitle,
  meta,
  actions,
  gutter = "edge",
  className,
}: PageHeaderProps) {
  const right = (meta || actions) && (
    <div className="ml-auto flex items-center gap-3 shrink-0">
      {meta && (
        <span className="hidden sm:inline text-2xs text-right whitespace-nowrap" style={{ color: "var(--ink-faint)" }}>
          {meta}
        </span>
      )}
      {actions}
    </div>
  );

  return (
    <div
      className={cn(
        "shrink-0",
        gutter === "edge" && "px-[var(--space-row-edge)] pt-4 pb-1",
        gutter === "page" && "px-[var(--space-page-x)] pt-4 pb-1",
        className,
      )}
    >
      <div className={cn("flex gap-3", actions ? "items-start" : "items-baseline")}>
        <h1 className="text-lg font-semibold leading-none min-w-0 truncate" style={{ color: "var(--ink-primary)" }}>
          {title}
        </h1>
        {right}
      </div>
      {subtitle && (
        <p className="text-sm mt-[var(--space-stack-xs)] max-w-[520px]" style={{ color: "var(--ink-muted)" }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
