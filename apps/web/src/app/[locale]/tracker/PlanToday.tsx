"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { listActions, createAction, updateAction, getPlannerStats, getPlannerSettings } from "@/api/client";
import type { ActionRead, PlannerStats, PlannerSettings } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ZoneHead } from "./ZoneHead";

const HORIZON_DAYS = 14;

// Action type → Today group. Manual/global/undated fall to "anytime".
const GROUP_OF: Record<string, string> = {
  prep: "deadlines",
  follow_up: "followups",
  apply: "apply",
  thank_you: "wrapup",
};
const GROUP_ORDER = ["deadlines", "followups", "apply", "wrapup", "anytime"];

// Fallback estimate by type, for rows written before est_minutes existed and for
// manual to-dos the user did not estimate. The engine now emits its own value
// (packages/domain/planner/rules.py DEFAULT_EST_MINUTES) — prefer that.
const EST_FALLBACK: Record<string, number> = {
  follow_up: 15, thank_you: 15, prep: 30, apply: 60, networking: 20, custom: 20, global: 15,
};

function estOf(a: ActionRead): number {
  return a.est_minutes ?? EST_FALLBACK[a.type] ?? 20;
}

function groupOf(a: ActionRead): string {
  if (!a.due_at && a.type !== "apply" && a.type !== "follow_up") return "anytime";
  return GROUP_OF[a.type] ?? "anytime";
}

// What counts against TODAY's capacity. The list itself spans a 14-day horizon
// so upcoming deadlines stay visible, but the cap is a per-day number: summing
// the whole horizon against it would compare two weeks of work to one day of
// room. Undated work counts (Anytime is "today if there's room"); work due later
// does not.
function countsTowardToday(a: ActionRead): boolean {
  const info = dueInfo(a);
  return info === null || info.today;
}

function fmtMinutes(m: number): string {
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (!h) return `${mm}m`;
  return mm ? `${h}h${String(mm).padStart(2, "0")}` : `${h}h`;
}

// Smallest-first until the excess is covered. Shared by the button's label and
// its handler so the count shown is exactly the set that moves.
function pickToDefer(candidates: ActionRead[], excess: number): ActionRead[] {
  const picked: ActionRead[] = [];
  let freed = 0;
  for (const a of candidates) {
    if (freed >= excess) break;
    picked.push(a);
    freed += estOf(a);
  }
  return picked;
}

/**
 * Plan · Today. Pending actions within a 14-day horizon, grouped by TYPE
 * (Deadlines / Follow-ups / Apply / Wrap-up / Anytime), in a two-column layout:
 * the action list (left) + the This-week triplet rail (right). Rows carry a
 * ✓ checkbox, a per-item estimate, one semantic due pill, and a recede-on-hover
 * snooze; a "Rest until Monday" batch-snooze and a done bar close it out.
 * Optimistic mutations are guarded exactly as in P0 (removingRef + add guard).
 */
export function PlanToday() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [actions, setActions] = useState<ActionRead[] | null>(null);
  const [stats, setStats] = useState<PlannerStats | null>(null);
  const [settings, setSettings] = useState<PlannerSettings | null>(null);
  const [error, setError] = useState(false);
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [resting, setResting] = useState(false);
  const [deferring, setDeferring] = useState(false);
  const removingRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const horizon = new Date(Date.now() + HORIZON_DAYS * 86400_000).toISOString();
      const [res, st, cfg] = await Promise.all([
        listActions({ due_on_or_before: horizon, include_undated: true }, token),
        getPlannerStats(undefined, token).catch(() => null),
        getPlannerSettings(token).catch(() => null),
      ]);
      setActions(res.items.filter((a) => !removingRef.current.has(a.id)));
      setStats(st);
      setSettings(cfg);
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  async function mutate(id: string, op: "complete" | "snooze") {
    removingRef.current.add(id);
    setActions((prev) => prev?.filter((a) => a.id !== id) ?? null);
    try {
      const token = await getToken();
      await updateAction(id, { op, snooze_days: 1 }, token);
    } catch {
      load();
    } finally {
      removingRef.current.delete(id);
    }
  }

  async function add() {
    if (adding) return;
    const title_ = title.trim();
    if (!title_) return;
    setAdding(true);
    try {
      const token = await getToken();
      await createAction({ type: "custom", title: title_ }, token);
      setTitle("");
      await load();
    } catch {
      // keep the typed title for retry
    } finally {
      setAdding(false);
    }
  }

  // Rest until Monday: snooze every current action to the next Monday.
  async function restUntilMonday() {
    if (resting || !actions || actions.length === 0) return;
    setResting(true);
    const now = new Date();
    const daysToMon = ((8 - now.getDay()) % 7) || 7; // 1..7 days to the NEXT Monday
    // Absolute local-midnight of next Monday, so overdue actions land ON Monday
    // (not merely +N days from a past due, which could stay in the past).
    const until = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysToMon).toISOString();
    const ids = actions.map((a) => a.id);
    ids.forEach((id) => removingRef.current.add(id));
    setActions([]);
    try {
      const token = await getToken();
      await Promise.all(ids.map((id) => updateAction(id, { op: "snooze", snooze_days: 1, snooze_until: until }, token)));
    } catch {
      load();
    } finally {
      ids.forEach((id) => removingRef.current.delete(id));
      setResting(false);
    }
  }

  // Overloaded-day escape hatch: push the smallest Anytime items to tomorrow
  // until today fits again. Anytime first because it is the only work with no
  // date attached to it — everything else is due today for a reason.
  async function deferToFit(candidates: ActionRead[], excess: number) {
    if (deferring || !candidates.length) return;
    setDeferring(true);
    const ids = pickToDefer(candidates, excess).map((a) => a.id);
    ids.forEach((id) => removingRef.current.add(id));
    setActions((prev) => prev?.filter((a) => !ids.includes(a.id)) ?? null);
    try {
      const token = await getToken();
      await Promise.all(ids.map((id) => updateAction(id, { op: "snooze", snooze_days: 1 }, token)));
    } catch {
      load();
    } finally {
      ids.forEach((id) => removingRef.current.delete(id));
      setDeferring(false);
    }
  }

  const items = actions ?? [];
  const grouped: Record<string, ActionRead[]> = {};
  for (const g of GROUP_ORDER) grouped[g] = [];
  for (const a of items) grouped[groupOf(a)].push(a);

  // Two different totals: the whole visible horizon (informational) vs what is
  // actually on the hook for today (what the cap governs).
  const estTotal = items.reduce((sum, a) => sum + estOf(a), 0);
  const todayItems = items.filter(countsTowardToday);
  const estToday = todayItems.reduce((sum, a) => sum + estOf(a), 0);
  const cap = settings?.daily_cap_minutes ?? 0;
  const isEmpty = actions !== null && actions.length === 0;
  const restsWeekend = !!settings?.rest_days?.some((d) => d === "sat" || d === "sun");
  const zoneSub = [
    items.length > 0 ? t("estMinutes", { minutes: estTotal }) : null,
    restsWeekend ? t("restWeekendNote") : null,
  ].filter(Boolean).join(" · ");

  return (
    <section className="w-full">
      <ZoneHead eyebrow={t("zoneEyebrowToday")} title={t("todayTitle")} sub={zoneSub || undefined} />
      <div className="grid gap-5 lg:grid-cols-[1fr_216px] lg:gap-6">
        {/* MAIN — action list */}
        <div className="min-w-0 space-y-5 order-2 lg:order-1">
          {!isEmpty && actions !== null && (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2 text-xs" style={{ color: "var(--ink-muted)" }}>
                <span>{t("todaySummary", { count: items.length, minutes: estTotal })}</span>
                <Button size="sm" variant="ghost" onClick={restUntilMonday} loading={resting}>{t("restUntilMon")}</Button>
              </div>
              {cap > 0 && (
                <CapacityBar
                  used={estToday}
                  cap={cap}
                  deferrable={todayItems.filter((a) => groupOf(a) === "anytime").sort((x, y) => estOf(x) - estOf(y))}
                  onDefer={deferToFit}
                  deferring={deferring}
                />
              )}
            </div>
          )}

          {/* Manual add */}
          <div className="flex items-center gap-2">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !adding) add(); }}
              placeholder={t("actionTitlePlaceholder")}
              className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
              style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            />
            <Button size="sm" onClick={add} disabled={!title.trim()} loading={adding}>{t("add")}</Button>
          </div>

          {actions === null ? (
            error ? (
              <div className="text-center py-8">
                <p className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
                <Button size="sm" variant="outline" onClick={load}>{t("retry")}</Button>
              </div>
            ) : (
              <div className="animate-pulse h-24" aria-hidden />
            )
          ) : isEmpty ? (
            /* Done bar */
            <div
              className="rounded-lg border px-4 py-4 text-center"
              style={{ borderColor: "var(--match-good-border, var(--border))", background: "var(--match-good-bg)" }}
            >
              <p className="text-sm font-semibold mb-0.5" style={{ color: "var(--match-good-fg)" }}>{t("todayCleared")}</p>
              <p className="text-xs" style={{ color: "var(--ink-muted)" }}>{t("todayEmpty")}</p>
            </div>
          ) : (
            <div className="space-y-5">
              {GROUP_ORDER.filter((g) => grouped[g].length > 0).map((g) => (
                <section key={g}>
                  <h3 className="text-2xs font-semibold uppercase tracking-wide mb-1 flex items-center gap-1.5" style={{ color: "var(--ink-muted)" }}>
                    {t(`planGroup.${g}`)}<span style={{ color: "var(--ink-faint)" }}>· {grouped[g].length}</span>
                    <span className="ml-auto font-normal tabular-nums" style={{ color: "var(--ink-faint)" }}>
                      {fmtMinutes(grouped[g].reduce((s, a) => s + estOf(a), 0))}
                    </span>
                  </h3>
                  <ul>
                    {grouped[g].map((a) => (
                      <ActionItem key={a.id} a={a} onComplete={() => mutate(a.id, "complete")} onSnooze={() => mutate(a.id, "snooze")} />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* RAIL — This week */}
        {stats && (
          <aside className="order-1 lg:order-2">
            <div className="lg:sticky lg:top-2">
              <div className="text-2xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-faint)" }}>{t("thisWeek")}</div>
              <div className="grid grid-cols-3 lg:grid-cols-1 gap-2.5">
                <Meter label={t("weekApplied")} value={stats.applied} target={stats.weekly_target.apply} />
                <Meter label={t("weekOutreach")} value={stats.outreach} target={stats.weekly_target.outreach} />
                <Meter label={t("weekFollowUps")} value={stats.follow_ups} target={stats.weekly_target.follow_up} />
              </div>
            </div>
          </aside>
        )}
      </div>
    </section>
  );
}

/**
 * Today's load against the workspace's daily cap. Three states — under, past the
 * 85% mark, over — because a plan that fills every available minute has no room
 * for the day going sideways; 85% is where capacity-planning practice says to
 * stop. Over-capacity offers a way out rather than just turning red: an overload
 * is a signal to re-decide, not a debt.
 *
 * Colour note: main has no danger or warn semantic tokens yet (the ui-reskin
 * line is adding them), so the near and over states share the existing
 * partial-match amber and lean on copy plus weight to separate them. Point the
 * `over` branch at the danger token once that work lands.
 */
function CapacityBar({ used, cap, deferrable, onDefer, deferring }: {
  used: number; cap: number;
  deferrable: ActionRead[];
  onDefer: (candidates: ActionRead[], excess: number) => void;
  deferring: boolean;
}) {
  const t = useTranslations("tracker");
  const pct = Math.round((used / cap) * 100);
  const state = pct > 100 ? "over" : pct > 85 ? "near" : "under";
  const fill = state === "under" ? "var(--primary)" : "var(--match-partial-fg)";
  const excess = used - cap;
  // Only offer the escape hatch when it can actually move the needle.
  const wouldMove = state === "over" ? pickToDefer(deferrable, excess).length : 0;

  return (
    <div>
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
        {wouldMove > 0 && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            loading={deferring}
            onClick={() => onDefer(deferrable, excess)}
          >
            {t("capacityDefer", { n: wouldMove })}
          </Button>
        )}
      </div>
    </div>
  );
}

type DueInfo = { today: boolean; days: number; warn: boolean };

// Semantic due label from due_at vs local today: "today" (warn) or "due Nd"
// (warn within a day). Undated actions get no pill (they read as "anytime").
function dueInfo(a: ActionRead): DueInfo | null {
  if (!a.due_at) return null;
  const due = new Date(a.due_at);
  if (isNaN(due.getTime())) return null;
  const now = new Date();
  const d0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const d1 = new Date(due.getFullYear(), due.getMonth(), due.getDate());
  const days = Math.round((d1.getTime() - d0.getTime()) / 86400_000);
  if (days <= 0) return { today: true, days: 0, warn: true };
  return { today: false, days, warn: days <= 1 };
}

function ActionItem({ a, onComplete, onSnooze }: { a: ActionRead; onComplete: () => void; onSnooze: () => void }) {
  const t = useTranslations("tracker");
  const info = dueInfo(a);
  const est = estOf(a);
  return (
    <li className="group flex items-center gap-2.5 py-2 border-b" style={{ borderColor: "var(--border)" }}>
      <button
        onClick={onComplete}
        aria-label={t("complete")}
        title={t("complete")}
        className="shrink-0 w-[18px] h-[18px] rounded-[5px] border grid place-items-center text-[11px] leading-none hover:bg-[var(--match-good-bg)]"
        style={{ borderColor: "var(--border-strong, var(--border))", color: "var(--match-good-fg)" }}
      >
        <span className="opacity-0 group-hover:opacity-80 transition-opacity">✓</span>
      </button>
      <span className="flex-1 min-w-0">
        <span className="block truncate text-sm" style={{ color: "var(--ink-secondary)" }}>
          {a.auto_generated && (
            <span className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle" style={{ background: "var(--primary)" }} title={t("autoGenerated")} aria-label={t("autoGenerated")} />
          )}
          {a.title}
        </span>
        <span className="block text-2xs mt-0.5" style={{ color: "var(--ink-faint)" }}>{t("estMinutes", { minutes: est })}</span>
      </span>
      <span className="shrink-0 w-[62px] flex justify-end">
        {info && (
          <span
            className="text-2xs font-semibold px-1.5 py-0.5 rounded-full whitespace-nowrap"
            style={info.warn
              ? { background: "var(--match-partial-bg)", color: "var(--match-partial-fg)" }
              : { color: "var(--ink-faint)", border: "1px solid var(--border)" }}
          >
            {info.today ? t("dueToday") : t("dueInDays", { n: info.days })}
          </span>
        )}
      </span>
      <button
        onClick={onSnooze}
        className="shrink-0 text-2xs px-2 py-1 rounded-md opacity-40 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
        style={{ color: "var(--ink-muted)" }}
      >
        {t("snoozeShort")}
      </button>
    </li>
  );
}

function Meter({ label, value, target }: { label: string; value: number; target: number }) {
  const pct = target > 0 ? Math.min(100, Math.round((value / target) * 100)) : 0;
  const done = target > 0 && value >= target;
  return (
    <div className="rounded-lg border p-2.5" style={{ borderColor: "var(--border)" }}>
      <div className="text-2xs uppercase tracking-wide mb-1" style={{ color: "var(--ink-faint)" }}>{label}</div>
      <div className="text-sm font-semibold tabular-nums" style={{ color: "var(--ink-primary)" }}>
        {value}<span className="text-2xs font-normal" style={{ color: "var(--ink-muted)" }}> / {target}</span>
      </div>
      <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: done ? "var(--match-good-fg)" : "var(--primary)" }} />
      </div>
    </div>
  );
}
