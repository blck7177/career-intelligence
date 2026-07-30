import type { ElementType, ReactNode } from "react";
import { cn } from "@/lib/utils";

export type BannerVariant = "info" | "warn" | "danger" | "success" | "neutral";

interface BannerProps {
  variant?: BannerVariant;
  /** sm = 8px/12px padding + 12px text (inline notes); md = 16px + 13px; lg = 24px (wizard-sized panels). */
  size?: "sm" | "md" | "lg";
  icon?: ElementType;
  /** Bold lead-in rendered inline before the body. No punctuation is added — existing copy ships its own. */
  title?: ReactNode;
  children: ReactNode;
  /** Rendered on its own row below the text. */
  action?: ReactNode;
  className?: string;
}

const TONE: Record<BannerVariant, { bg: string; border: string; fg: string }> = {
  info: { bg: "var(--info-bg)", border: "var(--info-border)", fg: "var(--info-fg)" },
  warn: { bg: "var(--warn-bg)", border: "var(--warn-border)", fg: "var(--warn-fg)" },
  danger: { bg: "var(--danger-bg)", border: "var(--danger-border)", fg: "var(--danger-fg)" },
  // success reuses --match-strong-*: that triple is already built by exactly this
  // construction at hue 155, so a separate --success-* would be a duplicate color.
  success: { bg: "var(--match-strong-bg)", border: "var(--match-strong-border)", fg: "var(--match-strong-fg)" },
  // neutral is Row's palette — it exists because two run statuses (queued,
  // cancelled) and one parse note are muted surfaces with nowhere else to go.
  neutral: { bg: "var(--muted)", border: "var(--border)", fg: "var(--ink-secondary)" },
};

/**
 * One status surface, five tones, replacing every hand-rolled notice on the
 * run pages, /profile and /workspace — which between them mixed raw Tailwind
 * blue/amber/rose/emerald with tokens, sometimes inside the same component.
 *
 * Plain function, no "use client" — runs/[run_id] renders it from a Server
 * Component.
 */
export function Banner({
  variant = "neutral",
  size = "md",
  icon: Icon,
  title,
  children,
  action,
  className,
}: BannerProps) {
  const tone = TONE[variant];
  return (
    <div
      className={cn(
        "rounded-lg border flex flex-col gap-[var(--space-stack-sm)]",
        size === "sm" && "px-3 py-2 text-xs",
        size === "md" && "p-[var(--space-surface-compact)] text-sm",
        size === "lg" && "p-[var(--space-surface-spacious)] text-sm",
        className,
      )}
      style={{ background: tone.bg, borderColor: tone.border, color: tone.fg }}
    >
      <div className={cn("flex items-start", size === "sm" ? "gap-1.5" : "gap-2")}>
        {Icon && <Icon size={size === "sm" ? 13 : 16} className="shrink-0 mt-px" />}
        <div className="min-w-0">
          {title && <span className="font-medium">{title}</span>}
          {children}
        </div>
      </div>
      {action}
    </div>
  );
}
