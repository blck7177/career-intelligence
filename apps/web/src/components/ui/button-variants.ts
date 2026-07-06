import { cn } from "@/lib/utils";

export type ButtonVariant = "default" | "secondary" | "outline" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonVariantsOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}

/**
 * Shared class-name builder for anything styled as a button — the <Button>
 * component uses it, and any <Link> standing in as a primary CTA should too,
 * so nav-level actions and real <button>s stay visually identical without
 * forcing a Link into a <button> element.
 *
 * Plain function, no "use client" — Server Components (e.g. page.tsx) call
 * this directly to style <Link> CTAs; it must not live in a client module.
 *
 * Depth is restrained on purpose: a 3-tier shadow (rest/hover/active) + 1px
 * hover lift + press-back on active, no gradients or animated shine.
 */
export function buttonVariants({ variant = "default", size = "md", className }: ButtonVariantsOptions = {}) {
  return cn(
    "inline-flex items-center justify-center rounded-lg font-medium",
    "transition-[transform,box-shadow,filter] duration-150 ease-out active:duration-75",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[var(--primary)]/45",
    "disabled:opacity-50 disabled:pointer-events-none",
    size === "sm" && "h-9 px-3.5 text-[13px]",
    size === "md" && "h-10 px-4 text-sm",
    size === "lg" && "h-11 px-6 text-sm",
    variant === "default" &&
      "bg-[var(--primary)] text-white shadow-[var(--shadow-btn-rest)] hover:shadow-[var(--shadow-btn-hover)] hover:-translate-y-px hover:brightness-95 active:translate-y-0 active:brightness-90 active:shadow-[var(--shadow-btn-active)]",
    variant === "secondary" &&
      "bg-[var(--secondary)] text-[var(--secondary-foreground)] shadow-[var(--shadow-btn-rest-soft)] hover:shadow-[var(--shadow-btn-hover-soft)] hover:-translate-y-px active:translate-y-0 active:brightness-95",
    variant === "outline" &&
      "border border-[var(--border)] bg-white text-[var(--foreground)] hover:bg-[var(--muted)] hover:shadow-[var(--shadow-btn-hover-outline)] hover:-translate-y-px active:translate-y-0 active:bg-[var(--muted)]",
    variant === "ghost" && "text-[var(--foreground)] hover:bg-[var(--muted)]",
    variant === "destructive" &&
      "bg-rose-600 text-white shadow-[var(--shadow-btn-rest)] hover:bg-rose-700 hover:shadow-[var(--shadow-btn-hover-destructive)] hover:-translate-y-px active:translate-y-0 active:bg-rose-800",
    className,
  );
}
