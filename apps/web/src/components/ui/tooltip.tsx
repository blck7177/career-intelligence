"use client";

import { Tooltip as BaseTooltip } from "@base-ui/react/tooltip";

export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return <BaseTooltip.Provider delay={300}>{children}</BaseTooltip.Provider>;
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactElement }) {
  return (
    <BaseTooltip.Root>
      <BaseTooltip.Trigger render={children} />
      <BaseTooltip.Portal>
        <BaseTooltip.Positioner sideOffset={8}>
          <BaseTooltip.Popup
            className="rounded-md bg-[var(--ink-primary)] px-2.5 py-1.5 text-xs font-medium text-white shadow-md
                       origin-[var(--transform-origin)] transition-[transform,opacity]
                       data-[starting-style]:opacity-0 data-[starting-style]:scale-90
                       data-[ending-style]:opacity-0 data-[ending-style]:scale-90"
          >
            {content}
          </BaseTooltip.Popup>
        </BaseTooltip.Positioner>
      </BaseTooltip.Portal>
    </BaseTooltip.Root>
  );
}
