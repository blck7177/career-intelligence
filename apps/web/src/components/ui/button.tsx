"use client";

import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
}

export function Button({
  className,
  variant = "default",
  size = "md",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium transition-all focus-visible:outline-none disabled:opacity-50 disabled:pointer-events-none",
        size === "sm" && "h-9 px-3.5 text-[13px]",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-11 px-6 text-sm",
        variant === "default" && "bg-[var(--primary)] text-white shadow-sm hover:opacity-90 hover:shadow",
        variant === "secondary" && "bg-[var(--secondary)] text-[var(--secondary-foreground)] hover:opacity-80",
        variant === "outline" && "border border-[var(--border)] bg-white text-[var(--foreground)] hover:bg-[var(--muted)]",
        variant === "ghost" && "text-[var(--foreground)] hover:bg-[var(--muted)]",
        variant === "destructive" && "bg-rose-600 text-white shadow-sm hover:bg-rose-700",
        className,
      )}
      {...props}
    />
  );
}
