"use client";

import { useTranslations } from "next-intl";
import type { ActionRead } from "@/api/client";

/** Fallback estimate by type, for rows written before est_minutes existed and
 *  for manual to-dos the user did not estimate.
 *
 *  This table is duplicated in packages/domain/planner/rules.py
 *  (DEFAULT_EST_MINUTES) — unavoidably, since this side has to render before
 *  any request is made, and that side has to file the commitment without
 *  trusting the client's arithmetic. The number shown here becomes the number
 *  stored as "what I agreed to", so the two must hold identical values;
 *  tests/tracker/test_planner_day.py parses this literal and asserts it. */
export const EST_FALLBACK: Record<string, number> = {
  follow_up: 15, thank_you: 15, prep: 30, apply: 60, networking: 20, custom: 20, global: 15,
};

export function estOf(a: ActionRead): number {
  return a.est_minutes ?? EST_FALLBACK[a.type] ?? 20;
}

export function fmtMinutes(m: number): string {
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (!h) return `${mm}m`;
  return mm ? `${h}h${String(mm).padStart(2, "0")}` : `${h}h`;
}

/** The capacity reading — label, track, the 85% mark, and the sentence under
 *  it. Shared by the Today card and the morning ritual: while you tick boxes in
 *  the ritual you are looking at the same reading you will be held to, and a
 *  second copy would be a second place for the 85% threshold and the three
 *  states to drift. */
export function CapacityMeter({ used, cap, trailing }: {
  used: number; cap: number; trailing?: React.ReactNode;
}) {
  const t = useTranslations("tracker");
  const pct = Math.round((used / cap) * 100);
  const state = pct > 100 ? "over" : pct > 85 ? "near" : "under";
  const fill = state === "under" ? "var(--primary)" : "var(--match-partial-fg)";
  return (
    <>
      <div className="flex items-center justify-between text-2xs mb-1" style={{ color: "var(--ink-muted)" }}>
        <span>{t("capacityTitle")}</span>
        <span className="tabular-nums">{fmtMinutes(used)} / {fmtMinutes(cap)}</span>
      </div>
      <div className="relative h-2 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
        {/* the "stop here" mark */}
        <span
          className="absolute top-0 bottom-0 w-px z-10"
          style={{ left: "85%", background: "var(--ink-faint)" }}
          aria-hidden
        />
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${Math.min(pct, 100)}%`, background: fill }}
        />
      </div>
      <div className="flex items-center gap-2 flex-wrap mt-1 text-2xs" style={{ color: "var(--ink-faint)" }}>
        {state === "over" ? (
          <span className="font-semibold" style={{ color: "var(--match-partial-fg)" }}>
            {t("capacityOver", { pct: pct - 100 })}
          </span>
        ) : state === "near" ? (
          <span style={{ color: "var(--match-partial-fg)" }}>{t("capacityNear", { pct })}</span>
        ) : (
          <span>{t("capacityUnder", { pct })}</span>
        )}
        <span>· {t("capacityHint")}</span>
        {trailing}
      </div>
    </>
  );
}
