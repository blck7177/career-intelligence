"use client";

import { Menu } from "@base-ui/react/menu";
import { cn } from "@/lib/utils";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({ className, children, ...props }: React.ComponentProps<typeof Menu.Popup>) {
  return (
    <Menu.Portal>
      <Menu.Positioner sideOffset={6} align="end" className="z-50">
        <Menu.Popup
          className={cn(
            "min-w-[180px] rounded-lg border border-[var(--border)] bg-white py-1 shadow-lg",
            "origin-[var(--transform-origin)] transition-[transform,opacity]",
            "data-[starting-style]:opacity-0 data-[starting-style]:scale-95",
            "data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
            className,
          )}
          {...props}
        >
          {children}
        </Menu.Popup>
      </Menu.Positioner>
    </Menu.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof Menu.Item>) {
  return (
    <Menu.Item
      className={cn(
        "flex items-center gap-2 px-3 py-2 text-sm text-[var(--ink-secondary)] cursor-pointer outline-none",
        "data-[highlighted]:bg-[var(--muted)] data-[highlighted]:text-[var(--ink-primary)]",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuSeparator() {
  return <Menu.Separator className="my-1 h-px bg-[var(--border)]" />;
}
