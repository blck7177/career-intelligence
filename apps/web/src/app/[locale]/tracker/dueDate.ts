// Relative, and structurally typed rather than importing ActionRead: this
// module is unit-tested, and vitest resolves no "@/" alias. Depending only on
// the one field it reads also means a change to ActionRead cannot break it.
import { daysBetween, localDateOf } from "../../../lib/quickParse";

/** Anything with a due instant — all these functions read of a to-do. */
type Dated = { due_at?: string | null };

/**
 * Which day a to-do is owed on, decided in the WORKSPACE's calendar.
 *
 * All three of these used to read `new Date().getDate()`, putting a user
 * working from another zone a whole day out: a to-do due at local midnight in
 * New York counts as today's from Tokyo the evening before. That was survivable
 * while the week strip only drew dots — now it prints minutes directly above a
 * capacity bar fed by these same functions, and two subtractable numbers that
 * disagree on one screen are not.
 *
 * `serverToday` is the date the server marked `is_today`. When it or the zone
 * is missing these report "unknown" rather than falling back to the browser
 * clock — the rule dayShift and Reschedule already follow. The cost is a moment
 * of no pill during load; the alternative is a confident wrong date.
 */
export type DueInfo = { today: boolean; days: number; warn: boolean };

export function dueInfo(
  a: Dated,
  tz: string | null,
  serverToday: string | null,
): DueInfo | null {
  if (!a.due_at || !tz || !serverToday) return null;
  const days = daysBetween(serverToday, localDateOf(a.due_at, tz));
  if (days <= 0) return { today: true, days: 0, warn: true };
  return { today: false, days, warn: days <= 1 };
}

/** Whether this to-do is part of what today is on the hook for. */
export function countsTowardToday(
  a: Dated,
  tz: string | null,
  serverToday: string | null,
): boolean {
  // Undated work counts, and that is a fact about the to-do — no clock needed.
  if (!a.due_at) return true;
  // A DATED to-do with no zone yet is not "anytime", it is unknown. dueInfo
  // returns null for both, so reading that null as "counts" would sweep every
  // dated item into today for as long as settings were still loading.
  if (!tz || !serverToday) return false;
  const info = dueInfo(a, tz, serverToday);
  return info !== null && info.today;
}

/**
 * Due before today and still open.
 *
 * A plain calendar-date comparison. The old form asked dueInfo whether the item
 * counted as today and then re-derived the boundary from the browser clock to
 * check whether it was actually earlier — two different calendars deciding one
 * question, which is exactly how they disagree.
 */
export function isOverdue(
  a: Dated,
  tz: string | null,
  serverToday: string | null,
): boolean {
  if (!a.due_at || !tz || !serverToday) return false;
  return localDateOf(a.due_at, tz) < serverToday;
}
