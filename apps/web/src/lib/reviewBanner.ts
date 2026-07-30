import type { WeeklyReviewRead } from "@/api/client";

/** Should the Plan view announce this weekly review?
 *
 *  Three ways to answer "no", and each wrong answer fails quietly in its own
 *  direction, which is why this is a function with tests rather than an
 *  expression inline in the JSX:
 *   - no review yet → nothing to announce (the beat has not run for this
 *     workspace, or it is brand new);
 *   - already read → announcing it again teaches the user the banner is noise;
 *   - dismissed THIS week → "later" means later today, not "never again". It is
 *     keyed by week precisely so next week's review still gets its one
 *     announcement; a boolean flag here would silently mute the feature for the
 *     rest of the session after a single click.
 */
export function shouldAnnounceReview(
  review: WeeklyReviewRead | null | undefined,
  dismissedWeek: string | null,
): boolean {
  if (!review) return false;
  if (review.read_at) return false;
  return dismissedWeek !== review.week_start;
}
