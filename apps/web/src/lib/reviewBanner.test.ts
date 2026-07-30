import { describe, expect, it } from "vitest";
import { reviewKey, shouldAnnounceReview } from "./reviewBanner";
import type { WeeklyReviewRead } from "@/api/client";

function review(over: Partial<WeeklyReviewRead> = {}): WeeklyReviewRead {
  return {
    week_start: "2026-07-13",
    stats: {
      week_start: "2026-07-13",
      applied: 6,
      outreach: 2,
      follow_ups: 3,
      weekly_target: { apply: 10, outreach: 5, follow_up: 6 },
      funnel: [],
      by_lane: {},
      by_channel: {},
      applied_total: 27,
      reached_interview: 6,
      interview_rate: 0.22,
    },
    narrative_md: "You applied to six roles.",
    degraded: false,
    generated_at: "2026-07-20T02:00:00Z",
    read_at: null,
    ...over,
  } as WeeklyReviewRead;
}

const USER = "user_aaa";

describe("shouldAnnounceReview", () => {
  it("announces an unread review", () => {
    expect(shouldAnnounceReview(review(), null, USER)).toBe(true);
  });

  it("says nothing while the review is still loading", () => {
    expect(shouldAnnounceReview(undefined, null, USER)).toBe(false);
  });

  it("says nothing when no review has been generated yet", () => {
    expect(shouldAnnounceReview(null, null, USER)).toBe(false);
  });

  it("stays quiet once the review has been read", () => {
    expect(shouldAnnounceReview(review({ read_at: "2026-07-20T09:00:00Z" }), null, USER)).toBe(false);
  });

  it("stays quiet for the review that was dismissed", () => {
    const r = review();
    expect(shouldAnnounceReview(r, reviewKey(r, USER), USER)).toBe(false);
  });

  it("announces NEXT week even after this week was dismissed", () => {
    // The failure this pins: a boolean "dismissed" flag would mute every future
    // review for the rest of the session after one click on Later.
    const dismissed = reviewKey(review(), USER);
    expect(shouldAnnounceReview(review({ week_start: "2026-07-20" }), dismissed, USER)).toBe(true);
  });

  it("announces a REGENERATED review for the same week", () => {
    // Dismissal is keyed by the review, not the week. A regenerated review has a
    // new generated_at, so it gets its own announcement — the client-side echo
    // of the server clearing read_at when the substance changed. Keying by week
    // alone would also carry one user's dismissal into the next user's session
    // after a client-side account switch, since the module is never reloaded.
    const dismissed = reviewKey(review(), USER);
    expect(shouldAnnounceReview(review({ generated_at: "2026-07-20T06:00:00Z" }), dismissed, USER)).toBe(true);
  });

  it("announces to a DIFFERENT user even after this one dismissed", () => {
    // The trap this pins: generated_at looks user-specific and is not. The
    // weekly beat writes every workspace's row in one transaction and postgres
    // now() is transaction-scoped, so a given week's reviews carry byte-identical
    // created_at across all users. Without the user component in the key, one
    // person's "Later" muted the next person's banner — the module survives a
    // client-side account switch because Clerk routes sign-out through the
    // router instead of reloading.
    const dismissed = reviewKey(review(), USER);
    expect(shouldAnnounceReview(review(), dismissed, "user_bbb")).toBe(true);
  });

  it("treats an empty-string read_at as unread rather than read", () => {
    // Defensive: a falsy timestamp is not a reading event. If the API ever sends
    // "" the honest failure is showing the banner once too often, not hiding a
    // review nobody saw.
    expect(shouldAnnounceReview(review({ read_at: "" }), null, USER)).toBe(true);
  });
});
