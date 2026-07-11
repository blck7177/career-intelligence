"use client";

import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = BaseDialog.Root;
export const DialogTrigger = BaseDialog.Trigger;

export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof BaseDialog.Popup>) {
  return (
    <BaseDialog.Portal>
      <BaseDialog.Backdrop
        className="fixed inset-0 z-40 bg-black/40 transition-opacity
                   data-[starting-style]:opacity-0 data-[ending-style]:opacity-0"
      />
      <BaseDialog.Popup
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2",
          "rounded-xl border border-[var(--border)] bg-white p-[var(--space-surface-spacious)] shadow-xl",
          "transition-[transform,opacity] data-[starting-style]:opacity-0 data-[starting-style]:scale-95",
          "data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
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

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof BaseDialog.Title>) {
  return <BaseDialog.Title className={cn("text-base font-semibold text-[var(--ink-primary)]", className)} {...props} />;
}

export function DialogDescription({ className, ...props }: React.ComponentProps<typeof BaseDialog.Description>) {
  return <BaseDialog.Description className={cn("text-sm text-[var(--ink-muted)] mt-1.5", className)} {...props} />;
}

export const DialogClose = BaseDialog.Close;
