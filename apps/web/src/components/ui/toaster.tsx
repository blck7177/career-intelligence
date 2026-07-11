"use client";

import { Toaster as SonnerToaster } from "sonner";

export { toast } from "sonner";

export function Toaster() {
  return (
    <SonnerToaster
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "!rounded-lg !border !border-[var(--border)] !bg-white !shadow-lg !text-[var(--ink-primary)]",
          title: "!text-sm !font-medium",
          description: "!text-xs !text-[var(--ink-muted)]",
          success: "!border-l-4 !border-l-emerald-500",
          error: "!border-l-4 !border-l-rose-500",
        },
      }}
    />
  );
}
