"use client";

import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// Sheet reuses the Dialog primitive (same a11y/focus-trap behavior) with a
// side-panel position + slide transition instead of a centered scale-in.
// A dedicated swipe-to-dismiss version can move to `vaul` later if we want
// the mobile drawer gesture; not needed for the desktop-first preview.

export const Sheet = BaseDialog.Root;
export const SheetTrigger = BaseDialog.Trigger;

export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof BaseDialog.Popup>) {
  return (
    <BaseDialog.Portal>
      <BaseDialog.Backdrop
        className="fixed inset-0 z-40 bg-black/40 transition-opacity
                   data-[starting-style]:opacity-0 data-[ending-style]:opacity-0"
      />
      <BaseDialog.Popup
        className={cn(
          "fixed right-0 top-0 z-50 h-full w-full max-w-sm bg-white border-l border-[var(--border)] shadow-xl p-6",
          "transition-transform duration-300 ease-out",
          "data-[starting-style]:translate-x-full data-[ending-style]:translate-x-full",
          className,
        )}
        {...props}
      >
        <BaseDialog.Close
          aria-label="Close"
          className="absolute right-4 top-4 text-[var(--ink-faint)] hover:text-[var(--ink-primary)] transition-colors"
        >
          <X size={16} />
        </BaseDialog.Close>
        {children}
      </BaseDialog.Popup>
    </BaseDialog.Portal>
  );
}

export function SheetTitle({ className, ...props }: React.ComponentProps<typeof BaseDialog.Title>) {
  return <BaseDialog.Title className={cn("text-base font-semibold text-[var(--ink-primary)]", className)} {...props} />;
}

export function SheetDescription({ className, ...props }: React.ComponentProps<typeof BaseDialog.Description>) {
  return <BaseDialog.Description className={cn("text-sm text-[var(--ink-muted)] mt-1.5", className)} {...props} />;
}
