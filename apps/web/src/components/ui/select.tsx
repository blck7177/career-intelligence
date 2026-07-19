"use client";

import { Select as BaseSelect } from "@base-ui/react/select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  label: string;
  value: string;
}

export function Select({
  options,
  value,
  onValueChange,
  placeholder,
  size = "md",
  className,
}: {
  options: SelectOption[];
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <BaseSelect.Root
      items={options}
      value={value}
      onValueChange={(v) => v !== null && onValueChange?.(v)}
    >
      <BaseSelect.Trigger
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-lg border border-[var(--border)]",
          "bg-white text-[var(--ink-primary)]",
          "focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/40 focus:border-[var(--primary)]",
          "data-[popup-open]:ring-2 data-[popup-open]:ring-[var(--primary)]/40",
          size === "sm" ? "h-8 px-2.5 text-xs rounded-md" : "h-10 px-3 text-sm",
          className,
        )}
      >
        <BaseSelect.Value placeholder={placeholder} className="min-w-0 flex-1 truncate text-left" />
        <BaseSelect.Icon>
          <ChevronDown size={14} className="text-[var(--ink-muted)]" />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner sideOffset={6} className="z-50">
          <BaseSelect.Popup
            className="rounded-lg border border-[var(--border)] bg-white py-1 shadow-lg
                       origin-[var(--transform-origin)] transition-[transform,opacity]
                       data-[starting-style]:opacity-0 data-[starting-style]:scale-95
                       data-[ending-style]:opacity-0 data-[ending-style]:scale-95"
          >
            <BaseSelect.List>
              {options.map((opt) => (
                <BaseSelect.Item
                  key={opt.value}
                  value={opt.value}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-[var(--ink-secondary)] cursor-pointer
                             data-[highlighted]:bg-[var(--muted)] data-[highlighted]:text-[var(--ink-primary)]
                             outline-none"
                >
                  <BaseSelect.ItemIndicator className="w-3.5 shrink-0">
                    <Check size={13} className="text-[var(--primary)]" />
                  </BaseSelect.ItemIndicator>
                  <BaseSelect.ItemText>{opt.label}</BaseSelect.ItemText>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  );
}
