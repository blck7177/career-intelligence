import { describe, expect, it } from "vitest";
import { shouldAnnounceReview } from "./reviewBanner";
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

describe("shouldAnnounceReview", () => {
  it("announces an unread review", () => {
    expect(shouldAnnounceReview(review(), null)).toBe(true);
  });

  it("says nothing while the review is still loading", () => {
    expect(shouldAnnounceReview(undefined, null)).toBe(false);
  });

  it("says nothing when no review has been generated yet", () => {
    expect(shouldAnnounceReview(null, null)).toBe(false);
  });

  it("stays quiet once the review has been read", () => {
    expect(shouldAnnounceReview(review({ read_at: "2026-07-20T09:00:00Z" }), null)).toBe(false);
  });

  it("stays quiet for the week that was dismissed", () => {
    expect(shouldAnnounceReview(review(), "2026-07-13")).toBe(false);
  });

  it("announces NEXT week even after this week was dismissed", () => {
    // The failure this pins: a boolean "dismissed" flag would mute every future
    // review for the rest of the session after one click on Later.
    expect(shouldAnnounceReview(review({ week_start: "2026-07-20" }), "2026-07-13")).toBe(true);
  });

  it("treats an empty-string read_at as unread rather than read", () => {
    // Defensive: a falsy timestamp is not a reading event. If the API ever sends
    // "" the honest failure is showing the banner once too often, not hiding a
    // review nobody saw.
    expect(shouldAnnounceReview(review({ read_at: "" }), null)).toBe(true);
  });
});
