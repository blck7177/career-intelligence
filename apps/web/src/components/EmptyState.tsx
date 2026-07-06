import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: React.ElementType;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  /** Compact = no dashed box / less padding, for narrow panels and sidebars. */
  compact?: boolean;
  className?: string;
}

/** Shared empty-state treatment: icon chip + title + optional hint/action. */
export function EmptyState({ icon: Icon, title, hint, action, compact, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "text-center flex flex-col items-center gap-3",
        compact ? "py-8 px-4" : "rounded-xl border border-dashed py-14 px-6",
        className,
      )}
      style={compact ? undefined : { borderColor: "var(--border)" }}
    >
      <span className={cn("flex items-center justify-center rounded-full bg-[var(--muted)] text-[var(--ink-muted)]", compact ? "w-8 h-8" : "w-10 h-10")}>
        <Icon size={compact ? 15 : 18} />
      </span>
      <div>
        <p
          className={cn("font-medium", compact ? "text-xs text-[var(--ink-muted)]" : "text-sm")}
          style={compact ? undefined : { color: "var(--foreground)" }}
        >
          {title}
        </p>
        {hint && (
          <p className="text-xs mt-1 max-w-xs" style={{ color: "var(--muted-foreground)" }}>
            {hint}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}
