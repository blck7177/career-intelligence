"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken, useApiUserId } from "@/hooks/useApiToken";
import { listActions, createAction, updateAction, getPlannerStats, getPlannerSettings, getPlannerWeek, getPlannerDay, commitPlannerDay, closePlannerDay } from "@/api/client";
import type { ActionRead, PlannerStats, PlannerSettings, PlannerWeek, PlannerWeekDay, PlannerDayRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { CapacityMeter, estOf, fmtMinutes } from "./capacity";
import { RitualWizard, type RitualResult } from "./RitualWizard";
import { ShutdownWizard, type ShutdownResult } from "./ShutdownWizard";
import { ZoneHead } from "@/components/ui/zone-head";
import { parseQuickAdd, dueAtFor, localMidnightUtc, addDays } from "@/lib/quickParse";

const HORIZON_DAYS = 14;

// Action type → Today group. Manual/global/undated fall to "anytime".
const GROUP_OF: Record<string, string> = {
  prep: "deadlines",
  follow_up: "followups",
  apply: "apply",
  thank_you: "wrapup",
};
const GROUP_ORDER = ["deadlines", "followups", "apply", "wrapup", "anytime"];

// Whose ritual, and which day, was waved away. Module scope so it survives
// leaving and re-entering the Plan tab — a prompt that returns every time you
// come back is one you learn to dismiss without reading — and keyed by the day
// so tomorrow morning still asks. Not persisted: skipping is a decision about
// this sitting, not a setting.
//
// The USER belongs in the key for the same reason it does in the review
// banner's (V5-C7): Clerk routes a sign-out through the Next router without
// reloading, so the module survives an account switch and a bare day key would
// mute the next person's morning.
let skippedRitual: string | null = null;

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

// The engine records the facts each auto to-do fired on (the payload contract in
// packages/domain/planner/rules.py); this turns them into the line under the
// title, so a generated row explains itself instead of just issuing an order.
// Manual rows and anything predating the contract have no payload and show less.
//
// These are a snapshot from the moment the rule fired, not a live count. A row
// deferred for a week still says the number it was created with, so the day
// counts read low rather than high — understating the case for acting is the
// safe direction for an error, and re-deriving them here would need fields
// (applied_at, the interview date) that ActionRead does not carry.
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function reasonOf(a: ActionRead, t: (k: string, v?: Record<string, string | number>) => string): string | null {
  const p = a.payload;
  if (!p) return null;
  switch (p.rule) {
    case "follow_up": {
      const days = num(p.days_since_applied);
      return days === null ? null : t("reasonFollowUp", { days });
    }
    case "thank_you": {
      const at = typeof p.interview_at === "string" ? new Date(p.interview_at) : null;
      if (!at || isNaN(at.getTime())) return null;
      return t("reasonThankYou", { when: at.toLocaleDateString(undefined, { month: "short", day: "numeric" }) });
    }
    case "check_in": {
      const days = num(p.days_since_interview);
      return days === null ? null : t("reasonCheckIn", { days });
    }
    case "apply_or_drop": {
      const days = num(p.days_planned);
      return days === null ? null : t("reasonApplyOrDrop", { days });
    }
    case "queue_refill": {
      const count = num(p.planned_count);
      const target = num(p.target);
      return count === null || target === null ? null : t("reasonQueueRefill", { count, target });
    }
    default:
      return null; // unrecognised rule → say nothing rather than guess
  }
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
  const userId = useApiUserId();
  const [actions, setActions] = useState<ActionRead[] | null>(null);
  const [stats, setStats] = useState<PlannerStats | null>(null);
  const [settings, setSettings] = useState<PlannerSettings | null>(null);
  const [week, setWeek] = useState<PlannerWeek | null>(null);
  const [error, setError] = useState(false);
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [resting, setResting] = useState(false);
  const [deferring, setDeferring] = useState(false);
  // undefined = still loading. `day.log` null = no row today (ritual not run);
  // day.done_* are measured live and arrive either way.
  const [day, setDay] = useState<PlannerDayRead | undefined>(undefined);
  const [shutdownOpen, setShutdownOpen] = useState(false);
  const [shutdownBusy, setShutdownBusy] = useState(false);
  const [ritualError, setRitualError] = useState(false);
  const [shutdownError, setShutdownError] = useState(false);
  // Which day the evening ritual is ending. Defaults to the server-labelled
  // today; a session running past midnight switches it to yesterday.
  const [closingDate, setClosingDate] = useState<string | null>(null);
  const [ritualOpen, setRitualOpen] = useState(false);
  const [ritualBusy, setRitualBusy] = useState(false);
  // "Skip" is a decision about this sitting, not a preference. Module scope so
  // it survives leaving and re-entering the Plan tab (see reviewBanner.ts for
  // the same call), keyed by day so tomorrow still asks.
  const [skipped, setSkipped] = useState<string | null>(skippedRitual);
  // Revocation is remembered by the TEXT that was rejected, not as a sticky flag.
  // A flag leaked: undo the date once and every later line silently stopped
  // parsing dates — the same silent failure this feature exists to avoid, just
  // pointing the other way.
  const [rejected, setRejected] = useState<{ date?: string; duration?: string; type?: string }>({});
  const removingRef = useRef<Set<string>>(new Set());

  // Dates resolve against the WORKSPACE's timezone, not the browser's, matching
  // the encoding the rules engine writes. Until settings arrive we know no zone,
  // so nothing is parsed as a date rather than guessing one and filing the to-do
  // a day off.
  const tz = settings?.timezone ?? null;
  const parsed = useMemo(() => {
    // Parse once to see what is there, then again honouring only the matches
    // whose text has not been rejected — so a rejection applies to that phrase
    // and stops applying the moment the user types something else.
    const probe = parseQuickAdd(title, tz);
    return parseQuickAdd(title, tz, {
      accept: {
        date: probe.date?.text !== rejected.date,
        duration: probe.duration?.text !== rejected.duration,
        type: probe.type?.text !== rejected.type,
      },
    });
  }, [title, tz, rejected]);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const horizon = new Date(Date.now() + HORIZON_DAYS * 86400_000).toISOString();
      // The strip is context, not the list itself — it degrades to absent
      // rather than failing the view.
      const [res, st, cfg, wk, dayState] = await Promise.all([
        listActions({ due_on_or_before: horizon, include_undated: true }, token),
        getPlannerStats(undefined, token).catch(() => null),
        getPlannerSettings(token).catch(() => null),
        getPlannerWeek(undefined, token).catch(() => null),
        getPlannerDay(token).catch(() => undefined),
      ]);
      setActions(res.items.filter((a) => !removingRef.current.has(a.id)));
      setStats(st);
      setSettings(cfg);
      setWeek(wk);
      setDay(dayState);
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  // The list updates optimistically, but the strip's per-day counts come from
  // the server (they fold in overdue and undated work, and that arithmetic
  // belongs in one place). Without this, clearing the last to-do left "today's
  // cleared" sitting next to a strip still showing dots on today.
  // The done bar and the shutdown summary are server-measured, so any mutation
  // that could change what is complete has to re-read them. Without this the
  // bar sits at its page-load value all day — the one thing it exists to avoid.
  const refreshDay = useCallback(async () => {
    try {
      const token = await getToken();
      setDay(await getPlannerDay(token));
    } catch {
      // Keep the last good reading rather than blanking the bar.
    }
  }, [getToken]);

  const refreshWeek = useCallback(async () => {
    try {
      const token = await getToken();
      setWeek(await getPlannerWeek(undefined, token));
    } catch {
      // Context, not content: keep the last good strip rather than blanking it.
    }
  }, [getToken]);

  async function mutate(id: string, op: "complete" | "snooze") {
    removingRef.current.add(id);
    setActions((prev) => prev?.filter((a) => a.id !== id) ?? null);
    try {
      const token = await getToken();
      await updateAction(id, { op, snooze_days: 1 }, token);
      await Promise.all([refreshWeek(), refreshDay()]);
    } catch {
      load();
    } finally {
      removingRef.current.delete(id);
    }
  }

  async function add() {
    if (adding) return;
    if (!(parsed.title || title.trim())) return;
    setAdding(true);
    try {
      const token = await getToken();
      await createAction(
        {
          // The parsed type is what finally lets a networking to-do be created
          // at all — this call used to hardcode "custom", so the outreach
          // counter could never be fed from the UI.
          type: parsed.type?.value ?? "custom",
          title: parsed.title || title.trim(),
          due_at: tz ? dueAtFor(parsed, tz) : undefined,
          est_minutes: parsed.duration?.minutes,
        },
        token,
      );
      setTitle("");
      setRejected({});
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
    // Days to the NEXT Monday, counted from the day the SERVER labelled today —
    // the strip is Monday-first, so the index IS the weekday and no browser
    // clock is involved. Absolute local-midnight target so overdue actions land
    // ON Monday rather than +N days from a past due, which could stay past.
    //
    // Resolved BEFORE the button enters its loading state: both of these bail
    // out, and setting it first would leave the spinner running forever on a
    // page whose strip or settings had not arrived.
    const todayIdx = week?.days.findIndex((d) => d.is_today) ?? -1;
    if (todayIdx < 0) return;
    const until = dayShift(7 - todayIdx);
    if (!until) return;
    setResting(true);
    const ids = actions.map((a) => a.id);
    ids.forEach((id) => removingRef.current.add(id));
    setActions([]);
    try {
      const token = await getToken();
      await Promise.all(ids.map((id) => updateAction(id, { op: "snooze", snooze_days: 1, snooze_until: until }, token)));
      await refreshWeek();
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
      await Promise.all([refreshWeek(), refreshDay()]);
    } catch {
      load();
    } finally {
      ids.forEach((id) => removingRef.current.delete(id));
      setDeferring(false);
    }
  }

  async function applyRitual({ keptIds, deferIds, dropIds }: RitualResult) {
    setRitualBusy(true);
    setRitualError(false);
    // Order matters: file the commitment FIRST. If the moves fail we have still
    // recorded what the user agreed to, which is the part that cannot be
    // reconstructed later; the to-dos are all still there to move by hand.
    try {
      const token = await getToken();
      const log = await commitPlannerDay(keptIds, token);
      setDay((prev) => (prev ? { ...prev, log } : prev));
      // Absolute target, not snooze_days: a relative snooze is measured from
      // due_at, so an overdue item moved "to tomorrow" would land on the day
      // after its ORIGINAL due date — still in the past, and straight back into
      // tomorrow's list. Same reason Rest-until-Monday sends a date.
      //
      // Anchored on the day the SERVER labelled today and encoded at local
      // midnight in the WORKSPACE timezone, which is the encoding due_at means
      // everywhere else. Building it from the browser clock instead put the
      // to-do on the wrong day of the strip for anyone not sitting in their
      // workspace's zone.
      const tomorrow = dayShift(1);
      if (!tomorrow) throw new Error("day or timezone unknown — refusing to guess a due date");
      await Promise.all([
        ...deferIds.map((id) =>
          updateAction(id, { op: "snooze", snooze_days: 1, snooze_until: tomorrow }, token),
        ),
        ...dropIds.map((id) => updateAction(id, { op: "dismiss", snooze_days: 1 }, token)),
      ]);
      setRitualOpen(false);
      await load();
      await refreshWeek();
    } catch {
      // Leave the wizard open so the user can retry without redoing three steps,
      // and say so — setError only renders while the list is still loading, so
      // on a loaded page it would have failed in complete silence.
      setRitualError(true);
    } finally {
      setRitualBusy(false);
    }
  }

  async function applyShutdown({ tomorrowIds, nextWeekIds, dropIds, reflection }: ShutdownResult) {
    setShutdownBusy(true);
    setShutdownError(false);
    try {
      const token = await getToken();
      // Same absolute-date reasoning as the morning ritual — and anchored on the
      // day being CLOSED, not on "now". Closing yesterday at 00:30, "tomorrow"
      // means the day you wake up into, which is already today; anchoring on now
      // would push it a day further than the user meant.
      const at = (days: number) => dayShift(days, closingDate ?? undefined);
      if (!at(1)) throw new Error("day or timezone unknown — refusing to guess a due date");
      await Promise.all([
        ...tomorrowIds.map((id) =>
          updateAction(id, { op: "snooze", snooze_days: 1, snooze_until: at(1)! }, token),
        ),
        ...nextWeekIds.map((id) =>
          updateAction(id, { op: "snooze", snooze_days: 7, snooze_until: at(7)! }, token),
        ),
        ...dropIds.map((id) => updateAction(id, { op: "dismiss", snooze_days: 1 }, token)),
      ]);
      // Close LAST here, the opposite order from the morning: done_est is
      // measured at close, and moving the leftovers first means the number is
      // taken against the day's final state rather than a half-tidied one.
      const log = await closePlannerDay(reflection, closingDate, token);
      setDay((prev) => (prev ? { ...prev, log } : prev));
      setShutdownOpen(false);
      await load();
      await refreshWeek();
    } catch {
      setShutdownError(true);
    } finally {
      setShutdownBusy(false);
    }
  }

  /** `base` (default: the server-labelled today) shifted by N days, encoded as
   *  local midnight in the workspace timezone — the same instant the backend
   *  writes for a due date. Returns undefined while the day or the timezone is
   *  still unknown, and every caller treats that as "do not move anything"
   *  rather than guessing from the browser clock. */
  function dayShift(days: number, base?: string): string | undefined {
    const tz = settings?.timezone;
    const from = base ?? week?.days.find((d) => d.is_today)?.date;
    if (!tz || !from) return undefined;
    return localMidnightUtc(addDays(from, days), tz);
  }

  // The day, as the SERVER labelled it in the week strip. Re-deriving it from
  // the browser clock is how a user in a different timezone gets asked twice —
  // or not at all — and it is the same off-by-one the strip already avoids.
  function todayKey(): string {
    const date = week?.days.find((d) => d.is_today)?.date;
    // No date yet means we cannot name the day, and an unnamed key would match
    // every day. Return null so the banner asks rather than silently hides.
    return date ? `${userId ?? "anon"}:${date}` : "";
  }

  function skipRitual() {
    const day = todayKey();
    if (!day) return;
    skippedRitual = day;
    setSkipped(day);
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
  // Whether TODAY is a rest day, taken from the strip the server already built
  // rather than re-derived from settings here: the strip knows which cell is
  // today in the workspace's timezone, and recomputing a weekday in the browser
  // is how the day-boundary bugs get back in. The old note only asked whether
  // sat/sun were in rest_days at all, so it read the same on a Tuesday.
  const isRestToday = !!week?.days.find((d) => d.is_today)?.is_rest;
  // Yesterday's leftovers: due before today and still open. dueInfo folds
  // everything past into today (that is what the capacity bar counts), so
  // "overdue" is read off due_at directly.
  const overdue = items.filter((a) => {
    if (!a.due_at) return false;
    const info = dueInfo(a);
    return info !== null && info.today && new Date(a.due_at) < startOfToday();
  });
  // Ask only once the day is actually known and the list has loaded: a banner
  // that flashes before the data arrives is a banner that gets clicked away.
  // The question is "has the morning ritual run today", and committed_est is
  // the direct answer. `log === null` was a proxy for it, and a proxy that
  // breaks in exactly the case that matters: closing a session past midnight
  // creates a row for the new day, which silently made the proxy false and shut
  // the banner off for a day nobody had planned.
  const askRitual =
    day !== undefined &&
    day.log?.committed_est == null &&
    actions !== null &&
    week !== null &&
    skipped !== todayKey();
  // (todayKey() is "" until the strip loads, which never equals a stored key —
  // so the banner asks rather than hides while the day is unknown.)
  const closed = !!day?.log?.closed_at;
  const zoneSub = [
    items.length > 0 ? t("estMinutes", { minutes: estTotal }) : null,
    isRestToday ? t("restDayNote") : null,
  ].filter(Boolean).join(" · ");

  return (
    <section className="w-full">
      <ZoneHead eyebrow={t("zoneEyebrowToday")} title={t("todayTitle")} sub={zoneSub || undefined} />

      {/* Morning ritual. Above the strip and the list because it is the thing
          to do BEFORE looking at either — once you have read the list you have
          already started planning in your head, informally, which is the habit
          the ritual replaces. */}
      {askRitual && (
        <div
          className="rounded-lg border px-4 py-3 mb-5 flex flex-wrap items-center gap-x-3 gap-y-2"
          style={{ borderColor: "var(--border)", background: "var(--muted)" }}
        >
          <b className="text-sm" style={{ color: "var(--ink-primary)" }}>{t("ritualBannerTitle")}</b>
          <span className="flex-1 min-w-0 text-xs" style={{ color: "var(--ink-secondary)" }}>
            {t("ritualBannerSummary", { count: items.length, carry: overdue.length })}
          </span>
          <Button size="sm" variant="outline" onClick={() => setRitualOpen(true)}>
            {t("ritualBannerStart")}
          </Button>
          <Button size="sm" variant="ghost" onClick={skipRitual}>{t("ritualBannerSkip")}</Button>
        </div>
      )}

      {(ritualError || shutdownError) && (
        <div
          className="rounded-lg border px-4 py-2 mb-4 text-xs"
          style={{ borderColor: "var(--match-partial-fg)", color: "var(--match-partial-fg)" }}
          role="alert"
        >
          {t("ritualFailed")}
        </div>
      )}

      <ShutdownWizard
        open={shutdownOpen}
        onOpenChange={setShutdownOpen}
        leftovers={todayItems}
        doneCount={day?.done_count ?? 0}
        doneEst={day?.done_est ?? 0}
        today={week?.days.find((d) => d.is_today)?.date ?? null}
        yesterday={(() => {
          const td = week?.days.find((d) => d.is_today)?.date;
          return td ? addDays(td, -1) : null;
        })()}
        closingDate={closingDate}
        onClosingDateChange={setClosingDate}
        onApply={applyShutdown}
        applying={shutdownBusy}
      />

      <RitualWizard
        open={ritualOpen}
        onOpenChange={setRitualOpen}
        actions={todayItems}
        overdue={overdue}
        cap={cap}
        onApply={applyRitual}
        applying={ritualBusy}
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_216px] lg:gap-6">
        {/* MAIN — action list */}
        <div className="min-w-0 space-y-5 order-2 lg:order-1">
          {/* Outside the !isEmpty block on purpose: a cleared day is exactly when
              you most need to see that Thursday has an onsite. The strip is the
              week's shape, not a decoration on today's list. */}
          {week && <WeekStrip week={week} />}
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

          {/* Done bar. Visible all day, not only on a cleared list: the point is
              to see the day accumulating while it happens. Finished to-dos leave
              the list the moment they are ticked, so without this the only
              evidence of a productive morning is an emptier list — which looks
              identical to a morning where nothing was there to begin with. */}
          {day !== undefined && actions !== null && (
            <div
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-2 text-xs"
              style={{ borderColor: "var(--border)" }}
            >
              <span style={{ color: "var(--ink-secondary)" }}>
                {t("doneToday", { n: day.done_count, minutes: fmtMinutes(day.done_est) })}
              </span>
              {day.log?.committed_est != null && (
                <span style={{ color: "var(--ink-faint)" }}>
                  · {t("doneVsCommitted", { minutes: fmtMinutes(day.log.committed_est) })}
                </span>
              )}
              <span className="flex-1" />
              {!closed && (
                <Button size="sm" variant="ghost" onClick={() => setShutdownOpen(true)}>
                  {t("shutdownOpen")}
                </Button>
              )}
            </div>
          )}

          {/* Manual add — parses what you type, and shows every guess it makes */}
          <div>
            <div className="flex items-center gap-2">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !adding) add(); }}
                placeholder={t("quickAddPlaceholder")}
                className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
                style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
              />
              <Button size="sm" onClick={add} disabled={!title.trim()} loading={adding}>{t("add")}</Button>
            </div>
            {/* Every match is shown and revocable: a silent wrong guess files the
                to-do on the wrong day and the user only finds out later. */}
            {(parsed.date || parsed.duration || parsed.type) && (
              <div className="flex items-center gap-1.5 flex-wrap mt-1.5 text-2xs">
                {parsed.date && (
                  <ParseChip tone="date" onRevoke={() => setRejected((r) => ({ ...r, date: parsed.date?.text }))} t={t}>
                    {parsed.date.date}
                  </ParseChip>
                )}
                {parsed.duration && (
                  <ParseChip tone="duration" onRevoke={() => setRejected((r) => ({ ...r, duration: parsed.duration?.text }))} t={t}>
                    {fmtMinutes(parsed.duration.minutes)}
                  </ParseChip>
                )}
                {parsed.type && (
                  <ParseChip tone="type" onRevoke={() => setRejected((r) => ({ ...r, type: parsed.type?.text }))} t={t}>
                    {t(`actionType.${parsed.type.value}`)}
                  </ParseChip>
                )}
                <span style={{ color: "var(--ink-faint)" }}>{t("quickAddRevokeHint")}</span>
              </div>
            )}
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
            <div
              className="rounded-lg border px-4 py-4 text-center"
              style={{ borderColor: "var(--match-good-border, var(--border))", background: "var(--match-good-bg)" }}
            >
              <p className="text-sm font-semibold mb-0.5" style={{ color: "var(--match-good-fg)" }}>
                {closed ? t("todayClosed") : t("todayCleared")}
              </p>
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
 * The week at a glance, above today's list. Interviews are the skeleton of a
 * day — you plan around them, not over them — so they have to be visible before
 * the day is planned, not discovered inside an application's timeline.
 *
 * Each cell shows its scheduled rounds (company, abbreviated) and a dot per
 * to-do due that day, capped so a heavy day reads as "heavy" rather than
 * becoming a wall of dots. Rest days are hatched and today is filled: the two
 * facts you need before deciding what to commit to.
 *
 * Dates come from the server already bucketed into the workspace's timezone, so
 * nothing here re-derives a day — parsing the ISO date locally would reintroduce
 * exactly the off-by-one the server-side contract exists to prevent.
 */
/**
 * One thing quick-add understood, and a way to say it got it wrong. Clicking
 * removes that guess and puts the text back in the title, which is the whole
 * point: parsing is only safe if it is visible and reversible.
 */
function ParseChip({ tone, onRevoke, t, children }: {
  tone: "date" | "duration" | "type";
  onRevoke: () => void;
  t: (k: string, v?: Record<string, string | number>) => string;
  children: React.ReactNode;
}) {
  const colors = {
    date: { bg: "var(--match-strong-bg)", fg: "var(--match-strong-fg)" },
    duration: { bg: "var(--match-partial-bg)", fg: "var(--match-partial-fg)" },
    type: { bg: "var(--match-good-bg)", fg: "var(--match-good-fg)" },
  }[tone];
  return (
    <button
      type="button"
      onClick={onRevoke}
      title={t("quickAddRevoke")}
      aria-label={t("quickAddRevoke")}
      className="px-1.5 rounded font-semibold hover:line-through"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {children}
      <span aria-hidden className="ml-1 opacity-60">×</span>
    </button>
  );
}

const MAX_DUE_DOTS = 4;

function WeekStrip({ week }: { week: PlannerWeek }) {
  const t = useTranslations("tracker");
  return (
    <div className="grid grid-cols-7 gap-1" role="list" aria-label={t("weekStripLabel")}>
      {week.days.map((d, i) => (
        <WeekCell key={d.date} day={d} index={i} t={t} />
      ))}
    </div>
  );
}

const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function WeekCell({ day, index, t }: {
  day: PlannerWeekDay;
  index: number;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  // Days arrive Monday-first, so position IS the weekday — deriving it from the
  // date string would mean parsing a date the server already resolved for us.
  const label = t(`weekdayShort.${WEEKDAY_KEYS[index]}`);
  const dd = Number(day.date.slice(8, 10));
  const dots = Math.min(day.due_count, MAX_DUE_DOTS);
  // interviews is optional in the generated type (server default), never absent in practice.
  const interviews = day.interviews ?? [];
  const title = [
    day.date,
    day.due_count > 0 ? t("weekStripDue", { n: day.due_count }) : null,
    ...interviews.map((i) => `${i.company}${i.round_type ? ` · ${i.round_type}` : ""}`),
  ].filter(Boolean).join(" · ");

  return (
    <div
      role="listitem"
      title={title}
      className="rounded-md border px-1.5 py-1 min-h-[46px] text-2xs"
      style={{
        borderColor: day.is_today ? "var(--primary)" : "var(--border)",
        background: day.is_today
          ? "var(--match-strong-bg)"
          : day.is_rest
            ? "repeating-linear-gradient(135deg, transparent 0 5px, var(--muted) 5px 7px)"
            : undefined,
        color: day.is_rest ? "var(--ink-faint)" : "var(--ink-muted)",
      }}
    >
      <div className="font-semibold" style={{ color: day.is_today ? "var(--ink-primary)" : undefined }}>
        {label} <span className="tabular-nums font-normal">{dd}</span>
      </div>
      <div className="flex flex-wrap items-center gap-0.5 mt-0.5">
        {interviews.slice(0, 2).map((iv, i) => (
          <span
            key={i}
            className="px-1 rounded-sm font-semibold truncate max-w-full"
            style={{ background: "var(--match-partial-bg)", color: "var(--match-partial-fg)" }}
          >
            {iv.company.split(/\s+/)[0].slice(0, 8)}
          </span>
        ))}
        {Array.from({ length: dots }).map((_, i) => (
          <span
            key={`d${i}`}
            className="inline-block w-1 h-1 rounded-full"
            style={{ background: "var(--primary)", opacity: 0.7 }}
            aria-hidden
          />
        ))}
      </div>
    </div>
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
  const excess = used - cap;
  // Only offer the escape hatch when it can actually move the needle.
  const wouldMove = pct > 100 ? pickToDefer(deferrable, excess).length : 0;

  return (
    <div>
      <CapacityMeter
        used={used}
        cap={cap}
        trailing={
          wouldMove > 0 ? (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              loading={deferring}
              onClick={() => onDefer(deferrable, excess)}
            >
              {t("capacityDefer", { n: wouldMove })}
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}

type DueInfo = { today: boolean; days: number; warn: boolean };

function startOfToday(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

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
  const reason = reasonOf(a, t);
  // Deferring once is ordinary rescheduling; twice means the item keeps getting
  // pushed, which is a decision to surface rather than a number to hide.
  const deferred = a.snooze_count >= 2;
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
            <span
              className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle"
              style={{ background: "var(--primary)" }}
              title={reason ? `${t("autoGenerated")} · ${reason}` : t("autoGenerated")}
              aria-label={t("autoGenerated")}
            />
          )}
          {a.title}
        </span>
        <span className="block text-2xs mt-0.5 truncate" style={{ color: "var(--ink-faint)" }}>
          {reason && <>{reason} · </>}
          {deferred && (
            <span style={{ color: "var(--match-partial-fg)", fontWeight: 600 }}>
              {t("deferredTimes", { n: a.snooze_count })}{" · "}
            </span>
          )}
          {t("estMinutes", { minutes: est })}
        </span>
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
