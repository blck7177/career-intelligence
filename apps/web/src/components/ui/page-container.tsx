import { cn } from "@/lib/utils";

interface PageContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "narrow" | "wide";
}

/**
 * Shared max-width + centering + gutter padding for page content. "narrow"
 * (672px) is for single-focus surfaces (forms, wizards, sparse lists); "wide"
 * (1024px) is for card/report-dense surfaces. Padding defaults to the shared
 * page gutter tokens — pass horizontal/vertical padding in className only for
 * a genuine exception, not as the normal way to size a page's padding. Plain
 * function, no "use client", so Server Component pages can call it directly.
 */
export function PageContainer({ variant = "wide", className, ...props }: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-[var(--space-page-x)] py-[var(--space-page-y)]",
        variant === "narrow" ? "max-w-[var(--container-narrow)]" : "max-w-[var(--container-wide)]",
        className,
      )}
      {...props}
    />
  );
}
