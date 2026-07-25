"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { getWeeklyReview } from "@/api/client";
import type { WeeklyReviewRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";

/** Plan · Review zone. The latest LLM weekly review (Wave 5). Renders the
 *  narrative when present; when generation degraded (narrative_md null) the card
 *  shows the number-only template with a small "summary unavailable" note.
 *  `undefined` = loading, `null` = no review generated yet (keep placeholder). */
export function ReviewZone() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [review, setReview] = useState<WeeklyReviewRead | null | undefined>(undefined);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      setReview(await getWeeklyReview(token));
      setError(false);
    } catch {
      setError(true);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  return (
    <section className="w-full">
      <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--ink-primary)" }}>{t("zoneReview")}</h2>
      {review === undefined ? (
        error ? (
          <div className="rounded-lg border border-dashed p-4 text-center" style={{ borderColor: "var(--border)" }}>
            <p className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
            <Button size="sm" variant="outline" onClick={load}>{t("retry")}</Button>
          </div>
        ) : (
          <div className="animate-pulse h-24 rounded-lg border" style={{ borderColor: "var(--border)" }} aria-hidden />
        )
      ) : review === null ? (
        <div className="rounded-lg border border-dashed p-4 text-center" style={{ borderColor: "var(--border)" }}>
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("reviewSoon")}</p>
          <p className="text-2xs mt-1" style={{ color: "var(--ink-faint)" }}>{t("reviewSoonSub")}</p>
        </div>
      ) : (
        <ReviewCard review={review} />
      )}
    </section>
  );
}

function ReviewCard({ review }: { review: WeeklyReviewRead }) {
  const t = useTranslations("tracker");
  const s = review.stats;
  const target = s.weekly_target;
  const ratePct = Math.round((s.interview_rate ?? 0) * 100);
  const benchPct = Math.round((s.benchmark_interview_rate ?? 0.08) * 100);

  return (
    <div className="rounded-lg border p-4 space-y-4" style={{ borderColor: "var(--border)" }}>
      {/* Header: week + generated timestamp */}
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--ink-primary)" }}>
          {t("reviewWeekOf", { date: s.week_start })}
        </span>
        <span className="text-2xs" style={{ color: "var(--ink-faint)" }}>
          {t("reviewGeneratedAt", { date: fmtTs(review.generated_at) })}
        </span>
      </div>

      {/* This-week triplet */}
      <div className="grid grid-cols-3 gap-3">
        <Meter label={t("weekApplied")} value={s.applied} target={target.apply} />
        <Meter label={t("weekOutreach")} value={s.outreach} target={target.outreach} />
        <Meter label={t("weekFollowUps")} value={s.follow_ups} target={target.follow_up} />
      </div>

      {/* Narrative (or degraded note) */}
      {review.narrative_md ? (
        <p className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
          {review.narrative_md}
        </p>
      ) : (
        <p className="text-xs italic" style={{ color: "var(--ink-muted)" }}>{t("reviewNarrativeUnavailable")}</p>
      )}

      {/* Conversion vs benchmark */}
      <div className="text-xs" style={{ color: "var(--ink-muted)" }}>
        {t("reviewInterviewRate")}:{" "}
        <span className="font-semibold tabular-nums" style={{ color: "var(--ink-primary)" }}>{ratePct}%</span>
        <span className="ml-1">
          ({s.reached_interview}/{s.applied_total} · {t("reviewVsTarget", { pct: benchPct })})
        </span>
      </div>

      {/* Pipeline snapshot */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs" style={{ color: "var(--ink-faint)" }}>
        {s.funnel.map((st) => (
          <span key={st.key}>
            {t(`funnelStage.${st.key}`)}{" "}
            <span className="font-semibold tabular-nums" style={{ color: "var(--ink-secondary)" }}>{st.count}</span>
          </span>
        ))}
      </div>

      {/* Honest replies footnote (pre-Gmail) */}
      {s.replies_are_manual && (
        <p className="text-2xs pt-1 border-t" style={{ color: "var(--ink-faint)", borderColor: "var(--border)" }}>
          {t("reviewRepliesNote")}
        </p>
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
