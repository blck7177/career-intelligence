import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

interface DetailBackBarProps {
  backHref: string;
  /** Verbatim copy — the existing strings already carry their own "←" glyph. */
  backLabel: string;
  title?: string;
  meta?: ReactNode;
  right?: ReactNode;
  className?: string;
}

/**
 * The 56px white bar above a detail page's scroll area: back link, page title,
 * right-aligned meta, and a right slot for status.
 *
 * Extracted from two byte-identical hand-rolled headers (runs/[run_id] and
 * fit-reports/[fit_report_id]) and given the title/meta/right shape so the
 * page body no longer repeats an h1 — the same slots PageHeader has, at the
 * bar height. px-7 became px-[var(--space-page-x)]: the same 28px, minus the
 * literal.
 *
 * Plain function, no "use client" — both call sites are async Server Components.
 */
export function DetailBackBar({ backHref, backLabel, title, meta, right, className }: DetailBackBarProps) {
  return (
    <header
      className={cn("h-14 flex items-center gap-4 px-[var(--space-page-x)] bg-[var(--card)] shrink-0", className)}
      style={{ borderBottom: "1px solid var(--border)" }}
    >
      <Link href={backHref} className="text-sm hover:underline shrink-0 whitespace-nowrap" style={{ color: "var(--primary)" }}>
        {backLabel}
      </Link>
      {title && (
        <h1 className="text-lg font-semibold leading-tight min-w-0 truncate" style={{ color: "var(--ink-primary)" }}>
          {title}
        </h1>
      )}
      {meta && (
        <span
          className="ml-auto hidden sm:block text-2xs whitespace-nowrap shrink-0"
          style={{ color: "var(--ink-faint)" }}
        >
          {meta}
        </span>
      )}
      {right && <div className={cn("flex items-center gap-3 shrink-0", meta ? undefined : "ml-auto")}>{right}</div>}
    </header>
  );
}
