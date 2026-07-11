import { cn } from "@/lib/utils";

interface OptionPillVariantsOptions {
  selected?: boolean;
  className?: string;
}

/**
 * Shared class-name builder for "selectable option" pills, mirroring
 * button-variants.ts/badge-variants.ts. Consolidates what were separately
 * hand-rolled pill implementations (Saved page status/favorites pills,
 * JobFilters active-filter chips) into one shape and one selected/
 * unselected color pair — selected now follows the app's --primary
 * "active" convention (TopBar, MatchStatStrip) rather than the older
 * --ink-primary dark-fill some of these call sites used before.
 *
 * Plain function, no "use client" — the Saved page's status pills are
 * <Link>s rendered from a Server Component.
 */
export function optionPillVariants({ selected = false, className }: OptionPillVariantsOptions = {}) {
  return cn(
    "inline-flex items-center gap-1.5 h-8 px-3.5 rounded-full text-sm font-medium transition-colors",
    selected
      ? "bg-[var(--primary)] text-white"
      : "bg-[var(--muted)] text-[var(--muted-foreground)] border border-[var(--border)] hover:text-[var(--ink-primary)]",
    className,
  );
}
