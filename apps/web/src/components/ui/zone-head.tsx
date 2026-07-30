import type { ElementType, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ZoneHeadProps {
  /** Uppercase 11px accent label. Pass this OR `title` (or both). */
  eyebrow?: string;
  title?: string;
  /** Right-aligned summary for "default"/"rail"; a second line under the title for "step". */
  sub?: ReactNode;
  variant?: "default" | "rail" | "step";
  /** "rail" only — leading lucide icon. */
  icon?: ElementType;
  /** "step" only — 1-based step number in a filled chip. */
  step?: number;
  /** Defaults to true for default/rail, false for step (a step head opens a card, not a page section). */
  divider?: boolean;
  className?: string;
}

/**
 * The app's single section head, promoted out of app/[locale]/tracker/ZoneHead.tsx.
 *
 * Three variants absorb what used to be four separate dialects:
 *  - "default" — the tracker zone shape (eyebrow + 15px title + right summary
 *    + hairline). Replaces the 12px uppercase h2s on /runs and the 13px
 *    semibold h2s on /workspace and /profile, all of which had no divider.
 *  - "rail"    — home's SidebarLabel density (icon + 12px label). Deliberately
 *    keeps its muted-icon/dark-label look and gets no purple eyebrow: it
 *    appears three or four times stacked in a ~270px rail, where uppercase
 *    accent caps would be noise.
 *  - "step"    — SearchSetupShell's private StepHeader (numbered chip + title
 *    + a second line below). Its title comes down to the 15px section rung:
 *    once the page title is pinned at 17px, a head inside a card must not tie it.
 *
 * Plain function, no "use client" — /runs renders it from a Server Component.
 */
export function ZoneHead({
  eyebrow,
  title,
  sub,
  variant = "default",
  icon: Icon,
  step,
  divider,
  className,
}: ZoneHeadProps) {
  const showDivider = divider ?? variant !== "step";
  const dividerStyle = showDivider ? { borderColor: "var(--border)" } : undefined;

  if (variant === "step") {
    return (
      <div className={cn("flex items-start gap-2.5", showDivider && "pb-2 border-b", className)} style={dividerStyle}>
        {step !== undefined && (
          <span
            className="w-6 h-6 rounded-full grid place-items-center shrink-0 mt-0.5 text-xs font-semibold"
            style={{ background: "var(--secondary)", color: "var(--secondary-foreground)" }}
          >
            {step}
          </span>
        )}
        <div className="min-w-0">
          {title && (
            <h2 className="text-[15px] font-semibold leading-tight" style={{ color: "var(--ink-primary)" }}>
              {title}
            </h2>
          )}
          {sub && (
            <p className="text-xs mt-[var(--space-stack-xs)]" style={{ color: "var(--ink-muted)" }}>
              {sub}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (variant === "rail") {
    return (
      <div
        className={cn("flex items-center gap-1.5", showDivider && "pb-2 mb-3 border-b", className)}
        style={dividerStyle}
      >
        {Icon && <Icon size={15} style={{ color: "var(--ink-muted)" }} />}
        <span className="text-xs font-semibold" style={{ color: "var(--ink-primary)" }}>
          {title ?? eyebrow}
        </span>
        {sub && (
          <span className="ml-auto text-2xs shrink-0 text-right" style={{ color: "var(--ink-faint)" }}>
            {sub}
          </span>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn("flex items-baseline gap-2.5", showDivider && "pb-2 mb-4 border-b", className)}
      style={dividerStyle}
    >
      {eyebrow && (
        <span
          className="text-2xs font-semibold uppercase shrink-0"
          style={{ color: "var(--primary)", letterSpacing: "0.12em" }}
        >
          {eyebrow}
        </span>
      )}
      {title && (
        <h2 className="text-[15px] font-semibold leading-tight truncate" style={{ color: "var(--ink-primary)" }}>
          {title}
        </h2>
      )}
      {sub && (
        <span className="ml-auto text-2xs shrink-0 text-right" style={{ color: "var(--ink-faint)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}
