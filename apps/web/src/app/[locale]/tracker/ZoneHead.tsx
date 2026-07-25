"use client";

import type { ReactNode } from "react";

/** Plan-view zone header (mockup .zonehead): an uppercase eyebrow label + a
 *  title + an optional right-aligned summary, over a divider. One shape for all
 *  three zones (Today / Pipeline / Review) so they read as a set. */
export function ZoneHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: ReactNode }) {
  return (
    <div
      className="flex items-baseline gap-2.5 pb-2 mb-4 border-b"
      style={{ borderColor: "var(--border)" }}
    >
      <span
        className="text-2xs font-bold uppercase shrink-0"
        style={{ color: "var(--primary)", letterSpacing: "0.12em" }}
      >
        {eyebrow}
      </span>
      <h2 className="text-[15px] font-semibold leading-tight truncate" style={{ color: "var(--ink-primary)" }}>
        {title}
      </h2>
      {sub && (
        <span className="ml-auto text-2xs shrink-0 text-right" style={{ color: "var(--ink-faint)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}
