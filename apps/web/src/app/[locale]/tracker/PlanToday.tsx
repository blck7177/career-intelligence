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

// Display-side effort estimate by type (the rules engine does not emit
// est_minutes; a per-type default is enough for the header total + per-item note).
const EST_MIN: Record<string, number> = {
  follow_up: 15, thank_you: 15, prep: 30, apply: 60, networking: 20, custom: 20, global: 15,
};

function groupOf(a: ActionRead): string {
  if (!a.due_at && a.type !== "apply" && a.type !== "follow_up") return "anytime";
  return GROUP_OF[a.type] ?? "anytime";
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

  const items = actions ?? [];
  const grouped: Record<string, ActionRead[]> = {};
  for (const g of GROUP_ORDER) grouped[g] = [];
  for (const a of items) grouped[groupOf(a)].push(a);

  const estTotal = items.reduce((sum, a) => sum + (EST_MIN[a.type] ?? 20), 0);
  const cap = settings?.daily_cap_minutes ?? 0;
  const overCap = cap > 0 && estTotal > cap;
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
            <div className="flex items-center justify-between gap-2 text-xs" style={{ color: "var(--ink-muted)" }}>
              <span>
                {t("todaySummary", { count: items.length, minutes: estTotal })}
                {overCap && <span className="ml-1.5" style={{ color: "var(--match-partial-fg)" }}>· {t("overCap", { cap })}</span>}
              </span>
              <Button size="sm" variant="ghost" onClick={restUntilMonday} loading={resting}>{t("restUntilMon")}</Button>
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
  const est = EST_MIN[a.type] ?? 20;
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
