import type { WeeklyReviewRead } from "@/api/client";

/** Identity of one review, for "Later" to remember.
 *
 *  The week alone is not enough. It is stored at module scope so a dismissal
 *  survives leaving and re-entering the Plan tab, and Clerk navigates a
 *  sign-out through the router rather than reloading the page — so a bare week
 *  key would carry one user's dismissal into the next user's session and mute
 *  their banner for that week. generated_at also makes a REGENERATED review
 *  announce itself again, which is the client-side echo of the server clearing
 *  read_at when the substance changed. */
export function reviewKey(review: WeeklyReviewRead): string {
  return `${review.week_start}:${review.generated_at}`;
}

/** Should the Plan view announce this weekly review?
 *
 *  Three ways to answer "no", and each wrong answer fails quietly in its own
 *  direction, which is why this is a function with tests rather than an
 *  expression inline in the JSX:
 *   - no review yet → nothing to announce (the beat has not run for this
 *     workspace, or it is brand new);
 *   - already read → announcing it again teaches the user the banner is noise;
 *   - this exact review was dismissed → "later" means later today, not "never
 *     again". Keyed by the review, so next week's still gets its one
 *     announcement; a boolean flag here would silently mute the feature for the
 *     rest of the session after a single click.
 */
export function shouldAnnounceReview(
  review: WeeklyReviewRead | null | undefined,
  dismissedKey: string | null,
): boolean {
  if (!review) return false;
  if (review.read_at) return false;
  return dismissedKey !== reviewKey(review);
}
