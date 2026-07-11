import { cn } from "@/lib/utils";

const METRIC_SIZES = {
  /** Every page gets at most one — the Fit Report score ring. */
  hero: "text-4xl font-bold tracking-[-0.02em] tabular-nums",
  /** Secondary but still call-out-worthy counts, e.g. the Dashboard rail. */
  stat: "text-2xl font-bold tracking-[-0.01em] tabular-nums",
} as const;

interface MetricProps extends React.HTMLAttributes<HTMLSpanElement> {
  size: keyof typeof METRIC_SIZES;
}

/**
 * Shared type scale for numbers that ARE the content (scores, counts) as
 * opposed to numbers embedded in a sentence. Plain function, no "use
 * client", so Server Component pages can call it directly — same pattern as
 * PageContainer.
 */
export function Metric({ size, className, ...props }: MetricProps) {
  return <span className={cn(METRIC_SIZES[size], className)} {...props} />;
}
