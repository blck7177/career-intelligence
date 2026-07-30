import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "destructive"
  | "warn"
  | "danger"
  | "info"
  | "match-strong"
  | "match-good"
  | "match-partial";

interface BadgeVariantsOptions {
  variant?: BadgeVariant;
  className?: string;
}

/**
 * Shared class-name builder for status/label chips, mirroring button-variants.ts.
 * The match-* variants read --match-*-bg/-fg from globals.css — the same tokens
 * JobDetailTabs already used — so e.g. a "with research" chip is identical no
 * matter which page renders it, instead of every call site hand-rolling its own
 * bg-emerald-100/bg-blue-100 className. Fit *score* bands (0-100, continuous
 * color) are a separate system in lib/matchBand.ts and don't belong here.
 *
 * Plain function, no "use client" — Badge is rendered from Server Components
 * (e.g. jobs/[job_id]/page.tsx) and must stay usable there.
 *
 * Note: variant="secondary" (neutral gray, --muted) is unrelated to the
 * --secondary CSS token (a purple brand tint, same hue as --primary). Don't
 * conflate them — THEME_CHIP in lib/matchBand.ts is the intentional
 * purple-chip use of --secondary and stays outside this variant set.
 */
export function badgeVariants({ variant = "default", className }: BadgeVariantsOptions = {}) {
  return cn(
    "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
    variant === "default" && "bg-[var(--ink-primary)] text-white",
    variant === "secondary" && "bg-[var(--muted)] text-[var(--muted-foreground)]",
    variant === "outline" && "border border-[var(--border)] text-[var(--ink-secondary)]",
    // destructive now reads the --danger-* triple instead of raw Tailwind rose,
    // so it lands in the same construction as warn/info and the match-* set.
    variant === "destructive" && "bg-[var(--danger-bg)] text-[var(--danger-fg)]",
    variant === "warn" && "bg-[var(--warn-bg)] text-[var(--warn-fg)]",
    variant === "danger" && "bg-[var(--danger-bg)] text-[var(--danger-fg)]",
    variant === "info" && "bg-[var(--info-bg)] text-[var(--info-fg)]",
    variant === "match-strong" && "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]",
    variant === "match-good" && "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]",
    variant === "match-partial" && "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]",
    className,
  );
}
