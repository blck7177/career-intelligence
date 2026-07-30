import type { WeeklyReviewRead } from "@/api/client";

/** Identity of one review AS SEEN BY ONE USER — what "Later" remembers.
 *
 *  The dismissal lives at module scope so it survives leaving and re-entering
 *  the Plan tab, and Clerk routes a sign-out through the Next router rather than
 *  reloading the page. So the key needs a user component or a dismissal crosses
 *  an account switch and mutes the next user's banner.
 *
 *  `generated_at` does NOT supply that, which is the trap: it looks
 *  user-specific and is not. The weekly beat writes every workspace's row inside
 *  ONE transaction, and postgres `now()` is transaction-scoped, so a given
 *  week's reviews carry byte-identical created_at across all users. It earns its
 *  place for a different reason — a REGENERATED review announces itself again,
 *  the client-side echo of the server clearing read_at when the substance
 *  changed. */
export function reviewKey(review: WeeklyReviewRead, userId: string | null): string {
  return `${userId ?? "anon"}:${review.week_start}:${review.generated_at}`;
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
  userId: string | null,
): boolean {
  if (!review) return false;
  if (review.read_at) return false;
  return dismissedKey !== reviewKey(review, userId);
}
