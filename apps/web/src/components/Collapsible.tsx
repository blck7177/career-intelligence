"use client";

interface CollapsibleProps {
  open: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * Animated show/hide via the grid-template-rows trick (0fr -> 1fr) instead of
 * a plain conditional render, so expand/collapse transitions smoothly without
 * measuring heights in JS.
 */
export function Collapsible({ open, children, className }: CollapsibleProps) {
  return (
    <div
      className={`grid transition-[grid-template-rows] duration-300 ease-in-out motion-reduce:transition-none ${className ?? ""}`}
      style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
    >
      <div className="overflow-hidden min-h-0">{children}</div>
    </div>
  );
}
