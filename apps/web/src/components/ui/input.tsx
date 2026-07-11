import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-10 w-full rounded-lg border border-[var(--border)] bg-white px-3 text-sm text-[var(--ink-primary)]",
        "placeholder:text-[var(--ink-faint)]",
        "focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/40 focus:border-[var(--primary)]",
        "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
        className,
      )}
      {...props}
    />
  );
}
