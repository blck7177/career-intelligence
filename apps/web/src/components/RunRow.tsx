import { ChevronRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { cardClassName } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { BadgeVariant } from "@/components/ui/badge-variants";
import { RunStatusStepper, type RunStatus } from "@/components/RunStatusStepper";
import { cn } from "@/lib/utils";

/**
 * One run status -> one chip tone, for every page that lists runs.
 *
 * This replaces two divergent helpers: runs/page.tsx's statusBadgeStyle (token
 * for succeeded/running, half-hardcoded oklch for failed/needs_review) and
 * SearchSetupShell's statusBadgeClass (bg-emerald-100 / bg-blue-100 /
 * bg-amber-100 / bg-rose-100).
 *
 * Two deliberate reads changed in the process:
 *  - running was purple (--secondary) on /runs and blue on /workspace; it is
 *    now one blue (--info), matching the "in progress" banner it sits beside
 *    on the detail page.
 *  - queued and cancelled used to render pixel-identically (both fell through
 *    to --muted). cancelled takes `outline`, so "terminal, no result" no
 *    longer looks like "waiting to start".
 */
export function runStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "succeeded":
      return "match-strong";
    case "running":
      return "info";
    case "needs_review":
      return "warn";
    case "failed":
      return "danger";
    case "cancelled":
      return "outline";
    default:
      return "secondary";
  }
}

interface RunRowProps {
  status: string;
  href: string;
  /** Resolved run-type label, e.g. "Discovery Run". */
  typeLabel: string;
  /** Resolved status label, e.g. "In Progress". */
  statusLabel: string;
  /** Pre-formatted timestamp (fmtTs). */
  timeLabel: string;
  className?: string;
}

/**
 * The shared run row, used by /runs (both groups) and by /workspace's Recent
 * Searches list. There used to be two implementations of this row with two
 * status vocabularies; the only real difference was density, so the /runs card
 * shape wins and one spec renders both.
 *
 * Labels arrive as resolved strings rather than being translated inside,
 * because /runs is a Server Component holding the "runs" namespace while
 * SearchSetupShell is a client component — the same contract
 * RunStatusStepper and JobReportContent already use.
 *
 * cardClassName rather than <Card>: an anchor must not contain a card div.
 */
export function RunRow({ status, href, typeLabel, statusLabel, timeLabel, className }: RunRowProps) {
  return (
    <Link
      href={href}
      className={cn(
        cardClassName,
        "flex items-center justify-between gap-4 p-[var(--space-row-card-y)_var(--space-row-card-x)]",
        "transition-shadow hover:shadow-md",
        className,
      )}
    >
      <span className="flex items-center gap-3 min-w-0">
        <RunStatusStepper status={status as RunStatus} size="sm" />
        <span className="min-w-0">
          <span className="block text-sm font-medium truncate" style={{ color: "var(--ink-primary)" }}>
            {typeLabel}
          </span>
          <span className="block text-xs mt-[var(--space-stack-xs)]" style={{ color: "var(--ink-faint)" }}>
            {timeLabel}
          </span>
        </span>
      </span>
      <span className="flex items-center gap-2 shrink-0">
        <Badge variant={runStatusVariant(status)}>{statusLabel}</Badge>
        <ChevronRight size={14} style={{ color: "var(--ink-faint)" }} />
      </span>
    </Link>
  );
}
