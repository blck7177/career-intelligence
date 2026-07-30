"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { getWeeklyReview, markWeeklyReviewRead } from "@/api/client";
import type { WeeklyReviewRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { reviewKey, shouldAnnounceReview } from "@/lib/reviewBanner";
import { PlanToday } from "./PlanToday";
import { PipelineZone } from "./PipelineZone";
import { ReviewZone } from "./ReviewZone";

// "Later" has to survive a tab switch: Plan unmounts when you go to Applications,
// and a banner that returns every time you come back is one you learn to swat
// without reading. Module scope rather than storage on purpose — this is a
// decision about this sitting, not a preference worth remembering forever.
// Keyed by the REVIEW (see reviewKey), not the week: a bare week key would carry
// the dismissal across a client-side account switch and mute the next user.
let dismissedReview: string | null = null;

/** The Plan sub-view: three stacked zones — Today (execution), Pipeline
 *  (health), Review (weekly). One scroll container.
 *
 *  The weekly review is fetched HERE, not inside ReviewZone, because two things
 *  now need it: the unread banner at the top and the zone at the bottom. Two
 *  independent fetches would let "mark read" update one copy and leave the other
 *  stale. */
export function PlanView() {
  const getToken = useApiToken();
  const [review, setReview] = useState<WeeklyReviewRead | null | undefined>(undefined);
  const [error, setError] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(dismissedReview);
  const reviewRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      setReview(await getWeeklyReview(token));
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => {
    load();
  }, [load]);

  const unread = shouldAnnounceReview(review, dismissed);

  async function openReview() {
    if (!review) return;
    reviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    // Optimistic: the banner has done its job the moment you act on it, and
    // leaving it up while the POST flies looks like the click missed. If the
    // request fails the banner returns on the next load — the right direction to
    // fail, unlike swallowing the error and never mentioning the review again.
    setReview({ ...review, read_at: new Date().toISOString() });
    try {
      const token = await getToken();
      setReview(await markWeeklyReviewRead(review.week_start, token));
    } catch {
      /* keep the optimistic state; a reload re-derives the truth from the server */
    }
  }

  function later() {
    if (!review) return;
    dismissedReview = reviewKey(review);
    setDismissed(dismissedReview);
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-[var(--space-row-edge)] py-6 space-y-10">
        {unread && review && (
          <ReviewBanner review={review} onOpen={openReview} onLater={later} />
        )}
        <PlanToday />
        <PipelineZone />
        <div ref={reviewRef} className="scroll-mt-4">
          <ReviewZone review={review} error={error} onRetry={load} />
        </div>
      </div>
    </div>
  );
}

function ReviewBanner({
  review,
  onOpen,
  onLater,
}: {
  review: WeeklyReviewRead;
  onOpen: () => void;
  onLater: () => void;
}) {
  const t = useTranslations("tracker");
  const s = review.stats;
  return (
    <div
      className="rounded-lg border px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2"
      style={{ borderColor: "var(--border)", background: "var(--muted)" }}
    >
      <b className="text-sm" style={{ color: "var(--ink-primary)" }}>
        {t("reviewBannerTitle")}
      </b>
      {/* Only facts the stats blob actually carries. The week prints as the
          stored ISO Monday rather than a client-computed range: deriving the end
          of the week in the browser reintroduces exactly the off-by-one that the
          server-side day boundary exists to prevent. */}
      <span className="flex-1 min-w-0 text-xs" style={{ color: "var(--ink-secondary)" }}>
        {t("reviewBannerSummary", {
          week: review.week_start,
          applied: s.applied,
          target: s.weekly_target.apply,
          rate: Math.round((s.interview_rate ?? 0) * 100),
        })}
      </span>
      <Button size="sm" variant="outline" onClick={onOpen}>
        {t("reviewBannerOpen")}
      </Button>
      <Button size="sm" variant="ghost" onClick={onLater}>
        {t("reviewBannerLater")}
      </Button>
    </div>
  );
}
