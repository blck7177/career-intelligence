"use client";

import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import { cn } from "@/lib/utils";

export const TabsRoot = BaseTabs.Root;
export const TabsPanel = BaseTabs.Panel;

export function TabsList({ className, ...props }: React.ComponentProps<typeof BaseTabs.List>) {
  return (
    <BaseTabs.List
      className={cn("relative flex gap-1 border-b border-[var(--border)]", className)}
      {...props}
    />
  );
}

export function Tab({ className, ...props }: React.ComponentProps<typeof BaseTabs.Tab>) {
  return (
    <BaseTabs.Tab
      className={cn(
        "relative z-[1] px-4 py-2 text-sm font-medium text-[var(--ink-muted)] transition-colors cursor-pointer",
        "data-[selected]:text-[var(--secondary-foreground)]",
        "outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40 rounded-t-md",
        className,
      )}
      {...props}
    />
  );
}

export function TabsIndicator({ className, ...props }: React.ComponentProps<typeof BaseTabs.Indicator>) {
  return (
    <BaseTabs.Indicator
      className={cn(
        "absolute top-0 bottom-0 z-0 rounded-t-md bg-[var(--secondary)]/60 border-b-2 border-[var(--primary)]",
        "transition-all duration-300 ease-out",
        "left-(--active-tab-left) w-(--active-tab-width)",
        className,
      )}
      {...props}
    />
  );
}
