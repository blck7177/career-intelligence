"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { createAction, updateAction, commitPlannerDay, closePlannerDay } from "@/api/client";
import type { ActionRead, PlannerWeek, PlannerWeekDay, FunnelResponse } from "@/api/client";
import { Button } from "@/components/ui/button";
import { CapacityMeter, estOf, fmtMinutes } from "./capacity";
import { RitualWizard, type RitualResult } from "./RitualWizard";
import { ShutdownWizard, type ShutdownResult } from "./ShutdownWizard";
import { ZoneHead } from "@/components/ui/zone-head";
import { toast } from "@/components/ui/toaster";
import type { PlannerData, PlannerSource } from "./usePlannerData";
import { ApplicationPeek } from "./ApplicationPeek";
import { parseQuickAdd, dueAtFor, localMidnightUtc, addDays } from "@/lib/quickParse";
import { countsTowardToday, dueInfo, isOverdue } from "./dueDate";
import { fmtClock, minutesOfDay } from "./scheduleGrid";

// Action type → Today group. Manual/global/undated fall to "anytime".
const GROUP_OF: Record<string, string> = {
  prep: "deadlines",
  follow_up: "followups",
  apply: "apply",
  thank_you: "wrapup",
};
const GROUP_ORDER = ["deadlines", "followups", "apply", "wrapup", "anytime"];

function groupOf(a: ActionRead): string {
  if (!a.due_at && a.type !== "apply" && a.type !== "follow_up") return "anytime";
  return GROUP_OF[a.type] ?? "anytime";
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

export function reasonOf(a: ActionRead, t: (k: string, v?: Record<string, string | number>) => string): string | null {
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
 *
 * All server state lives in usePlannerData; this component owns only what is
 * local to the sitting (the compose box, which wizard is open, in-flight flags).
 */
export function PlanToday({
  data, onShowPipeline, onOpenSchedule, selectedApplicationId, onClearSelected, onApplicationsChanged,
}: {
  data: PlannerData;
  onShowPipeline?: () => void;
  /** An application picked in the sidebar. The panel is shared: a to-do opened
   *  from the list and an application opened from the sidebar are the same
   *  surface, so only one can be showing. */
  selectedApplicationId?: string | null;
  onClearSelected?: () => void;
  /** The panel changed which list an application belongs in (a drop moves it
   *  from the queue to closed). The sidebar's list is not part of the planner
   *  store — see useApplicationsList — so it is re-read by its owner. */
  onApplicationsChanged?: () => void;
  /** Switch the shell to the Week sub-view. The strip has promised this jump
   *  since V3 ("V8 落地后改为跳周排程") — the schedule view now exists, so a
   *  cell click finally goes where the cell points. */
  onOpenSchedule: () => void;
}) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  // Every server-side source the view reads, plus the two ways to write to the
  // list. Which sources a mutation dirties is declared at each call site rather
  // than remembered — see usePlannerData for why. The store itself is owned by
  // PlanView: the Pipeline zone renders the same alerts and the same funnel, so
  // one of them holding a private copy is a guaranteed disagreement.
  const { actions, stats, settings, week, day, funnel, error, reload, refresh, mutateActions, patchDayLog } = data;
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [resting, setResting] = useState(false);
  const [deferring, setDeferring] = useState(false);
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
  // Revocation is remembered by the TEXT that was rejected, not as a sticky flag.
  // A flag leaked: undo the date once and every later line silently stopped
  // parsing dates — the same silent failure this feature exists to avoid, just
  // pointing the other way.
  const [rejected, setRejected] = useState<{ date?: string; duration?: string; type?: string }>({});
  // The to-do whose application is showing in the side panel. Holding the whole
  // action (not just an id) keeps the panel's header and reason line rendering
  // from the same row the user clicked, even after the list refetches.
  const [peek, setPeek] = useState<ActionRead | null>(null);
  // Where focus goes when the panel closes after an action. A dialog normally
  // returns focus to what opened it, but acting from the peek removes that row
  // optimistically, so there is nothing to return to and the keyboard user
  // lands on <body>. Closing WITHOUT acting (Esc, ×, overlay) leaves the row in
  // place and is left alone. Verified by reading, not by executing: there is no
  // jsdom in this repo.
  const listRef = useRef<HTMLDivElement>(null);

  // Dates resolve against the WORKSPACE's timezone, not the browser's, matching
  // the encoding the rules engine writes. Until settings arrive we know no zone,
  // so nothing is parsed as a date rather than guessing one and filing the to-do
  // a day off.
  const tz = settings?.timezone ?? null;
  // The server's idea of today, which is the only authority on the day
  // boundary. Null until the week arrives, and never guessed from the browser.
  const serverToday = week?.days.find((d) => d.is_today)?.date ?? null;
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

  // The evening close freezes done_est; a morning ritual writes committed_est
  // and leaves done_est NULL, which is a planned day, not a finished one. While
  // the day is still loading this reads open — the permissive direction, and
  // the server is the one that decides (it 409s a late reopen).
  const dayIsOpen = day?.log?.done_est == null;

  // The list updates optimistically, but the strip's per-day counts come from
  // the server (they fold in overdue and undated work, and that arithmetic
  // belongs in one place). Without this, clearing the last to-do left "today's
  // cleared" sitting next to a strip still showing dots on today.
  // The done bar and the shutdown summary are server-measured, so any mutation
  // that could change what is complete has to re-read them. Without this the
  // bar sits at its page-load value all day — the one thing it exists to avoid.
  //
  // What each op dirties, and why it is not just "everything":
  //   week  — every op changes what is open on some day.
  //   day   — the done bar counts completions; snooze/dismiss change what is
  //           still owed against the day's commitment.
  //   stats — ONLY completing: the triplet counts *completed* networking and
  //           follow-up actions (count_completed_by_type_in_range).
  //   funnel— ONLY completing: repo.complete() writes an `action_completed`
  //           event, which is what the check-in alert measures staleness from.
  //           snooze() and dismiss() write no event, so the funnel is untouched.
  async function mutate(id: string, op: "complete" | "snooze" | "dismiss"): Promise<boolean> {
    const dirties: PlannerSource[] =
      op === "complete" ? ["week", "day", "stats", "funnel"] : ["week", "day"];
    // Snooze sends an ABSOLUTE target. The repository measures a relative
    // snooze from due_at, so an overdue to-do "moved to tomorrow" lands the day
    // after its ORIGINAL due date — still in the past, and the button reads as
    // doing nothing. V6-C5 fixed this for the three wizard defers and V7-C2 for
    // the Applications row; the Today row's own snooze and the peek's
    // "Tomorrow" button were the two that still went out relative.
    const tomorrow = op === "snooze" ? dayShift(1) : undefined;
    const ok = await mutateActions(
      [id],
      (token) => updateAction(id, { op, snooze_days: 1, ...(tomorrow ? { snooze_until: tomorrow } : {}) }, token),
      dirties,
    );
    // The ✓ box is 18px and the whole row is clickable next to it, so a
    // mis-tick is ordinary. Offered only while the server would still accept
    // it: once the day is closed its done_est is frozen, and a button whose
    // request comes back 409 is worse than no button.
    if (ok && op === "complete" && dayIsOpen) {
      toast(t("completedToast"), { action: { label: t("undo"), onClick: () => undoComplete(id) } });
    }
    return ok;
  }

  /** Put a completion back. Not a snooze: an undated to-do has no due_at to
   *  restore, so a snooze would invent one and count the restore as a
   *  postponement. `reload()` rather than a refresh because the row has to
   *  reappear in the list, which is the one source `refresh` cannot re-read. */
  async function undoComplete(id: string) {
    try {
      const token = await getToken();
      // snooze_days is inert for this op but the generated body type requires
      // it (pydantic gives it a default, which openapi-typescript reads as
      // required) — every other call site spells it out the same way.
      await updateAction(id, { op: "reopen", snooze_days: 1 }, token);
      await reload();
      // Announced, not just performed. The toast outlives this view — switch to
      // Applications and click Undo and the reopen still lands, but reload()
      // repaints a tree nobody is looking at, so without this the success path
      // is the only silent one while the failure path still speaks.
      toast(t("undoDone"));
    } catch {
      toast(t("undoFailed"));
    }
  }

  /** "Not needed" is the one row action with a consequence worth stating: the
   *  suppression set remembers it, so the rule will not raise it again. Said
   *  only after the call lands — announcing it optimistically would promise
   *  something that a failed request did not do. */
  async function dismissFromPeek(a: ActionRead): Promise<boolean> {
    const ok = await mutate(a.id, "dismiss");
    if (ok) toast(t("peekDismissToast"));
    return ok;
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
      await reload();
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
    try {
      // Nothing is completed here, only moved, so the done bar cannot change:
      // the strip is the only source this dirties.
      await mutateActions(
        ids,
        (token) =>
          Promise.all(
            ids.map((id) => updateAction(id, { op: "snooze", snooze_days: 1, snooze_until: until }, token)),
          ),
        ["week"],
      );
    } finally {
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
    // Absolute target, like every other defer. "Anytime" is a grouping by TYPE,
    // not by date (groupOf), so this pool routinely holds dated — including
    // OVERDUE — work: a custom or networking to-do keeps its due date and still
    // lands here. A relative snooze on one of those moves it to the day after
    // its ORIGINAL due date, leaving it overdue, still counted against today,
    // and the capacity bar unmoved — which is the one thing this button exists
    // to do. Missed when V7-C5 fixed the other three call sites.
    const tomorrow = dayShift(1);
    try {
      await mutateActions(
        ids,
        (token) =>
          Promise.all(
            ids.map((id) =>
              updateAction(id, { op: "snooze", snooze_days: 1, ...(tomorrow ? { snooze_until: tomorrow } : {}) }, token),
            ),
          ),
        ["week", "day"],
      );
    } finally {
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
      patchDayLog(log);
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
      // reload() already re-reads the strip; the extra refresh is carried over
      // verbatim from before this hook existed so the refactor stays a refactor.
      await reload();
      await refresh("week");
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
      patchDayLog(log);
      setShutdownOpen(false);
      // Same carried-over double read of the strip as the morning ritual.
      await reload();
      await refresh("week");
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

  async function skipRitual() {
    // "Skip" commits to everything already on the plate rather than recording
    // nothing. The plan said so, and it is right for three reasons: the banner
    // stops asking because the day HAS been planned (not because a variable in
    // this tab says to hide it, which no reload survives), the weekly
    // comparison keeps a baseline for the day instead of a hole, and the two
    // bugs a module flag brought with it — lost on refresh, shared across a
    // client-side account switch — cannot exist at all.
    if (ritualBusy) return;
    setRitualBusy(true);
    setRitualError(false);
    try {
      const token = await getToken();
      const log = await commitPlannerDay(todayItems.map((a) => a.id), token);
      patchDayLog(log);
    } catch {
      setRitualError(true);
    } finally {
      setRitualBusy(false);
    }
  }

  const items = actions ?? [];
  const grouped: Record<string, ActionRead[]> = {};
  for (const g of GROUP_ORDER) grouped[g] = [];
  for (const a of items) grouped[groupOf(a)].push(a);

  // Two different totals: the whole visible horizon (informational) vs what is
  // actually on the hook for today (what the cap governs).
  const estTotal = items.reduce((sum, a) => sum + estOf(a), 0);
  const todayItems = items.filter((a) => countsTowardToday(a, tz, serverToday));
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
  // Overdue = its workspace-local due date is before the server's today. The
  // old form asked dueInfo whether it counted as today and then re-derived the
  // boundary from the browser clock to see if it was actually earlier — two
  // different calendars deciding one question.
  const overdue = items.filter((a) => isOverdue(a, tz, serverToday));
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
    week !== null;
  const closed = !!day?.log?.closed_at;
  // The week's next hard commitment — the one thing that should shape a day
  // before anything on the to-do list does (the digest principle: lead with
  // what cannot move).
  const nextInterview = (() => {
    for (const d of week?.days ?? []) {
      const iv = d.interviews ?? [];
      if (iv.length > 0) return { company: iv[0].company, day: d.date.slice(5) };
    }
    return null;
  })();
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
            {nextInterview && (
              <> {t("ritualBannerInterview", { company: nextInterview.company, day: nextInterview.day })}</>
            )}
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

      {/* The application behind whichever to-do you clicked. Ticking a row is a
          decision; this is the context for it, without leaving the day. */}
      <ApplicationPeek
        action={peek}
        // A to-do wins when both are set: it is the more specific subject, and
        // clicking a row while the sidebar has a selection should show the row.
        applicationId={peek ? null : selectedApplicationId ?? null}
        tz={tz}
        serverToday={serverToday}
        onClose={() => {
          const rowGone = peek !== null && !(actions ?? []).some((a) => a.id === peek.id);
          setPeek(null);
          onClearSelected?.();
          if (rowGone) requestAnimationFrame(() => listRef.current?.focus());
        }}
        onComplete={(a) => mutate(a.id, "complete")}
        onSnooze={(a) => mutate(a.id, "snooze")}
        onDismiss={dismissFromPeek}
        reason={(a) => reasonOf(a, t)}
        onApplicationChanged={() => refresh("funnel")}
        // Dropping or rescheduling from the panel changes rows, not just
        // readings: `reload()` is the only path that re-reads the action list,
        // and the sidebar keeps its own list that has to be told separately.
        onActionsChanged={() => { void reload(); onApplicationsChanged?.(); }}
      />

      <div className="grid gap-5 min-[900px]:grid-cols-[minmax(0,1fr)_300px] min-[900px]:gap-5">
        {/* MAIN — action list */}
        <div ref={listRef} tabIndex={-1} className="min-w-0 space-y-5 order-2 min-[900px]:order-1 outline-none">
          {/* Outside the !isEmpty block on purpose: a cleared day is exactly when
              you most need to see that Thursday has an onsite. The strip is the
              week's shape, not a decoration on today's list. */}
          {week && <WeekStrip week={week} onOpen={onOpenSchedule} cap={cap} tz={tz} />}
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
                {/* 🌙 rides the done bar rather than the empty state: the plan
                    asked for a closed day to READ as closed, and it has to hold
                    until the next morning — "see you at tomorrow's digest" is
                    the promise the ritual makes. A marker that only appears on
                    an empty list disappears the moment anything new comes due. */}
                {closed && "🌙 "}
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
                <Button size="sm" variant="outline" onClick={reload}>{t("retry")}</Button>
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
                      <ActionItem
                        key={a.id}
                        a={a}
                        tz={tz}
                        serverToday={serverToday}
                        onComplete={() => mutate(a.id, "complete")}
                        onSnooze={() => mutate(a.id, "snooze")}
                        onOpen={() => setPeek(a)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* RAIL — This week + today's digest + pipeline snapshot */}
        {(stats || funnel) && (
          <aside className="order-1 min-[900px]:order-2 space-y-4">
            <div className="min-[900px]:sticky min-[900px]:top-2 space-y-4">
              {stats && (
                <div>
                  <div className="text-2xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-faint)" }}>{t("thisWeek")}</div>
                  <div className="grid grid-cols-3 min-[900px]:grid-cols-1 gap-2.5">
                    <Meter label={t("weekApplied")} value={stats.applied} target={stats.weekly_target.apply} />
                    <Meter label={t("weekOutreach")} value={stats.outreach} target={stats.weekly_target.outreach} />
                    <Meter label={t("weekFollowUps")} value={stats.follow_ups} target={stats.weekly_target.follow_up} />
                  </div>
                </div>
              )}
              {/* `due` excludes the overdue ones: countsTowardToday is
                  (undated ∪ due today ∪ overdue), so passing its size beside an
                  overdue count printed the late work twice, in a line that
                  reads as two disjoint sets. */}
              <Digest due={todayItems.length - overdue.length} overdue={overdue.length} week={week} tz={tz} t={t} />
              <PipelineSnapshot funnel={funnel} onShowPipeline={onShowPipeline} t={t} />
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


function WeekStrip({ week, onOpen, cap, tz }: { week: PlannerWeek; onOpen: () => void; cap: number; tz: string | null }) {
  const t = useTranslations("tracker");
  // role="group", not "list": the cells are now buttons, and a button inside a
  // listitem role loses its button semantics for assistive tech.
  return (
    <div className="grid grid-cols-7 gap-1" role="group" aria-label={t("weekStripLabel")}>
      {week.days.map((d, i) => (
        <WeekCell key={d.date} day={d} index={i} onOpen={onOpen} cap={cap} tz={tz} t={t} />
      ))}
    </div>
  );
}

const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** "9:30" for an instant, read in the workspace zone. Empty when the zone is
 *  unknown — the same refusal to guess the rest of Today now makes. Built on
 *  the schedule grid's own two functions so the strip and the grid can never
 *  print different times for one block. */
function hhmm(iso: string, tz: string | null): string {
  if (!tz) return "";
  const m = minutesOfDay(iso, tz);
  return m === null ? "" : fmtClock(m);
}

function WeekCell({ day, index, onOpen, cap, tz, t }: {
  day: PlannerWeekDay;
  index: number;
  onOpen: () => void;
  /** Daily cap, for the load bar. 0 = not configured, so no bar is drawn. */
  cap: number;
  /** Workspace zone. Times are read in it, never in the browser's — the server
   *  bucketed these instants with it, so any other zone could print an hour
   *  belonging to the neighbouring day inside this cell. */
  tz: string | null;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  // Days arrive Monday-first, so position IS the weekday — deriving it from the
  // date string would mean parsing a date the server already resolved for us.
  const label = t(`weekdayShort.${WEEKDAY_KEYS[index]}`);
  const dd = Number(day.date.slice(8, 10));
  // interviews is optional in the generated type (server default), never absent in practice.
  const interviews = day.interviews ?? [];
  const blocks = day.blocks ?? [];
  const owed = day.due_est_minutes ?? 0;
  // What the day HOLDS: placed to-dos plus interviews of known length. Kept in
  // one place here rather than in each renderer — the schedule grid's day
  // footer answers the same question and must not reach a different number.
  const known = interviews.filter((iv) => typeof iv.duration_minutes === "number");
  const held = (day.scheduled_est_minutes ?? 0)
    + known.reduce((sum, iv) => sum + (iv.duration_minutes ?? 0), 0);
  const unknownRounds = interviews.length - known.length;
  const pct = cap > 0 ? Math.round((held / cap) * 100) : 0;

  const title = [
    day.date,
    day.due_count > 0 ? t("weekStripDue", { n: day.due_count }) : null,
    ...interviews.map((i) => `${i.company}${i.round_type ? ` · ${i.round_type}` : ""}`),
    ...blocks.map((b) => b.title),
  ].filter(Boolean).join(" · ");

  return (
    // A real <button>, not a div with handlers: Tab reaches it and Enter fires
    // it for free, and rowKeyboard.test.ts forbids the hand-rolled shape. The
    // strip only ever shows the CURRENT week, which is also what the schedule
    // view opens to — so the jump carries no date and cannot disagree with it.
    <button
      type="button"
      onClick={onOpen}
      title={`${title} — ${t("stripOpenWeek")}`}
      aria-label={`${title} — ${t("stripOpenWeek")}`}
      className="flex flex-col gap-0.5 rounded-md border px-1.5 py-1.5 min-h-[82px] text-2xs text-left"
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
      <span className="font-semibold" style={{ color: day.is_today ? "var(--ink-primary)" : undefined }}>
        {label} <span className="tabular-nums font-normal">{dd}</span>
      </span>

      {/* Interviews first: they are the day's fixed skeleton, and the same
          amber the schedule grid uses for them. */}
      {interviews.slice(0, 2).map((iv, i) => (
        <span
          key={`iv${i}`}
          className="block truncate rounded-sm px-1 font-semibold"
          style={{ background: "var(--warn-bg)", color: "var(--warn-fg)" }}
        >
          <span className="tabular-nums">{hhmm(iv.at, tz)}</span>{" "}
          {iv.company.split(/\s+/)[0].slice(0, 8)}
        </span>
      ))}

      {/* Then what you chose to put there — the grid's accent for placed work.
          Done blocks are dimmed: a cleared day should not look untouched. */}
      {blocks.slice(0, 2).map((b) => (
        <span
          key={b.action_id}
          className="block truncate rounded-sm px-1 font-semibold"
          style={{
            background: day.is_today ? "var(--card)" : "var(--accent)",
            color: "var(--accent-foreground)",
            opacity: b.status === "done" ? 0.55 : 1,
            textDecoration: b.status === "done" ? "line-through" : undefined,
          }}
        >
          <span className="tabular-nums">{hhmm(b.at, tz)}</span> {b.title}
        </span>
      ))}

      <span className="mt-auto tabular-nums">
        {day.is_rest && day.due_count === 0 && blocks.length === 0
          ? t("stripRest")
          : [
              day.due_count > 0 ? t("stripOwed", { n: day.due_count, minutes: fmtMinutes(owed) }) : null,
              held > 0 ? t("stripHeld", { minutes: fmtMinutes(held) }) : null,
              unknownRounds > 0 ? "+?" : null,
            ].filter(Boolean).join(" · ") || t("stripClear")}
      </span>

      {cap > 0 && (
        <span className="block h-1 rounded-full overflow-hidden" style={{ background: "var(--muted)" }} aria-hidden>
          <span
            className="block h-full rounded-full"
            style={{
              width: `${Math.min(100, pct)}%`,
              // Over the cap is the one thing here worth an alarm colour; the
              // 85% mark is where the capacity bar already starts warning.
              background: pct > 100 ? "var(--danger-fg)" : pct > 85 ? "var(--warn-fg)" : "var(--primary)",
            }}
          />
        </span>
      )}
    </button>
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


function ActionItem({ a, tz, serverToday, onComplete, onSnooze, onOpen }: {
  a: ActionRead;
  tz: string | null;
  serverToday: string | null;
  onComplete: () => void;
  onSnooze: () => void;
  onOpen: () => void;
}) {
  const t = useTranslations("tracker");
  const info = dueInfo(a, tz, serverToday);
  const est = estOf(a);
  const reason = reasonOf(a, t);
  // Deferring once is ordinary rescheduling; twice means the item keeps getting
  // pushed, which is a decision to surface rather than a number to hide.
  const deferred = a.snooze_count >= 2;
  return (
    // Clicking the row opens the peek; the two buttons that DO something stop
    // the event so a tick never also opens a panel. The title is itself a
    // button with no handler of its own — its click bubbles to this one, which
    // is what makes the row reachable by keyboard (Tab, Enter) without a second
    // code path or a nested-interactive double fire.
    <li
      onClick={onOpen}
      className="group flex items-center gap-2.5 py-2 border-b cursor-pointer"
      style={{ borderColor: "var(--border)" }}
    >
      <button
        onClick={(e) => { e.stopPropagation(); onComplete(); }}
        aria-label={t("complete")}
        title={t("complete")}
        className="shrink-0 w-[18px] h-[18px] rounded-[5px] border grid place-items-center text-[11px] leading-none hover:bg-[var(--match-good-bg)]"
        style={{ borderColor: "var(--border-strong, var(--border))", color: "var(--match-good-fg)" }}
      >
        <span className="opacity-0 group-hover:opacity-80 transition-opacity">✓</span>
      </button>
      <button type="button" className="flex-1 min-w-0 text-left" title={t("peekOpenHint")}>
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
      </button>
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
        onClick={(e) => { e.stopPropagation(); onSnooze(); }}
        className="shrink-0 text-2xs px-2 py-1 rounded-md opacity-40 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
        style={{ color: "var(--ink-muted)" }}
      >
        {t("snoozeShort")}
      </button>
    </li>
  );
}

const DIGEST_INTERVIEWS = 2;
const SNAPSHOT_ALERTS = 2;

/**
 * Today in one line: what is due, what is late, and the next hard commitments.
 *
 * The digest principle — lead with what cannot move. Counts come from the same
 * two sets the capacity bar uses, so the rail and the bar can never disagree
 * about how much today holds.
 *
 * Times are formatted in the WORKSPACE's timezone, not the browser's. Without a
 * timezone we print the day and company but no clock time: a 10:00 that is
 * really 13:00 is worse than no time at all, and this is the one place a
 * traveller would be misled.
 */
function Digest({ due, overdue, week, tz, t }: {
  due: number;
  overdue: number;
  week: PlannerWeek | null;
  /** The workspace timezone, from settings — PlannerWeek does not carry one. */
  tz: string | null;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  const upcoming: string[] = [];
  // Start at the day the SERVER labelled today, not at Monday. Scanning the
  // whole week printed Monday's finished screen as a "next commitment" and let
  // it consume one of the two slots, so on Friday the onsite six hours away did
  // not appear at all — in the card whose whole job is to lead with what cannot
  // move. Past days are dropped by index (no clock involved); today's own
  // earlier rounds are dropped by comparing instants, which is zone-independent.
  const todayIdx = week?.days.findIndex((d) => d.is_today) ?? -1;
  const from = todayIdx >= 0 ? todayIdx : 0;
  const now = Date.now();
  for (let i = from; i < (week?.days.length ?? 0) && upcoming.length < DIGEST_INTERVIEWS; i++) {
    const d = week!.days[i];
    // Days arrive Monday-first, so the index IS the weekday — no date parsing.
    const label = t(`weekdayShort.${WEEKDAY_KEYS[i]}`);
    for (const iv of d.interviews ?? []) {
      if (upcoming.length >= DIGEST_INTERVIEWS) break;
      const at = new Date(iv.at);
      if (!isNaN(at.getTime()) && at.getTime() < now) continue;
      const clock = tz && !isNaN(at.getTime())
        ? at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz })
        : null;
      upcoming.push(clock ? `${label} ${clock} ${iv.company}` : `${label} ${iv.company}`);
    }
  }

  if (due === 0 && overdue === 0 && upcoming.length === 0) return null;

  return (
    <div className="rounded-lg border px-3 py-2.5 text-2xs leading-relaxed" style={{ borderColor: "var(--border)" }}>
      <b style={{ color: "var(--ink-primary)" }}>{t("digestTitle")}</b>
      <span style={{ color: "var(--ink-muted)" }}>
        {" · "}
        {t("digestCounts", { due, overdue })}
        {upcoming.map((s) => (
          <span key={s}>{" · "}{s}</span>
        ))}
      </span>
    </div>
  );
}

/**
 * Pipeline health beside today's work, so a day of ticking to-dos cannot hide
 * an empty funnel. Read-only — acting on an alert (confirming a ghosting) stays
 * in the Pipeline zone, one click away, where the consequence is spelled out.
 */
function PipelineSnapshot({ funnel, onShowPipeline, t }: {
  funnel: FunnelResponse | null;
  onShowPipeline?: () => void;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  if (!funnel) return null;
  const alerts = funnel.alerts ?? [];
  return (
    <div className="rounded-lg border px-3 py-2.5" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="text-2xs font-semibold uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>
          {t("pipelineSnapshot")}
        </span>
        {onShowPipeline && (
          <button type="button" onClick={onShowPipeline} className="ml-auto text-2xs hover:underline" style={{ color: "var(--primary)" }}>
            {t("pipelineSnapshotMore")}
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-2xs" style={{ color: "var(--ink-muted)" }}>
        {(funnel.stages ?? []).map((s, i) => (
          <span key={s.key} className="whitespace-nowrap">
            {i > 0 && <span style={{ color: "var(--border)" }}>› </span>}
            {t(`funnelStage.${s.key}`)}{" "}
            <b className="tabular-nums" style={{ color: "var(--ink-primary)" }}>{s.count}</b>
          </span>
        ))}
      </div>
      {alerts.length > 0 && (
        <ul className="mt-2 pt-2 space-y-1 text-2xs" style={{ borderTop: "1px dashed var(--border)", color: "var(--ink-muted)" }}>
          {alerts.slice(0, SNAPSHOT_ALERTS).map((al, i) => (
            <li key={i}>
              <span style={{ color: al.severity === "warn" ? "var(--match-partial-fg)" : "var(--ink-faint)" }}>
                {al.severity === "warn" ? "⚠ " : "◦ "}
              </span>
              {t(al.message_key, al.context as Record<string, string | number>)}
            </li>
          ))}
          {alerts.length > SNAPSHOT_ALERTS && (
            <li style={{ color: "var(--ink-faint)" }}>{t("pipelineSnapshotMoreAlerts", { n: alerts.length - SNAPSHOT_ALERTS })}</li>
          )}
        </ul>
      )}
    </div>
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
