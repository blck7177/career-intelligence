import { cn } from "@/lib/utils";

/**
 * Exported as a bare string too, so an element that cannot be wrapped in <Card>
 * can still wear its chrome — a clickable <Link> row, for instance, since an
 * anchor must not contain a block-level card div. Same reasoning as
 * row.tsx's rowClassName and button-variants.ts.
 */
export const cardClassName = "rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-sm";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn(cardClassName, className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5 p-[var(--space-surface-default)] pb-0", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-[var(--space-surface-default)]", className)} {...props} />;
}
