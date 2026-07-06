"use client";

import { Loader2 } from "lucide-react";
import { buttonVariants, type ButtonVariant, type ButtonSize } from "./button-variants";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner before children and disables the button — no need to hand-roll a Loader2 conditional at each call site. */
  loading?: boolean;
  /**
   * Adds a single soft diagonal sheen that loops across the button. Reserve
   * for the one or two highest-intent primary actions on a page (e.g. "Start
   * discovery") — this is a rare accent, not a default button treatment.
   */
  shimmer?: boolean;
}

export function Button({
  className,
  variant = "default",
  size = "md",
  loading = false,
  shimmer = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={buttonVariants({ variant, size, className: cn(shimmer && "relative overflow-hidden", className) })}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {shimmer && !loading && !disabled && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-1/3 animate-button-shimmer pointer-events-none"
          style={{ background: "linear-gradient(115deg, transparent, oklch(100% 0 0 / 0.35), transparent)" }}
        />
      )}
      {loading && <Loader2 size={size === "sm" ? 12 : 14} className="animate-spin mr-1.5" />}
      {children}
    </button>
  );
}
