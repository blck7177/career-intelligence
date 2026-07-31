"use client";

import { useTranslations } from "next-intl";
import type { WeeklyReviewRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ZoneHead } from "@/components/ui/zone-head";
import { fmtTs } from "@/lib/utils";

/** Plan · Review zone. The latest LLM weekly review (Wave 5). Renders the
 *  narrative when present; when generation degraded (narrative_md null) the card
 *  shows the number-only template with a small "summary unavailable" note.
 *  `undefined` = loading, `null` = no review generated yet (keep placeholder).
 *
 *  The review is owned by PlanView (V5-C2): the unread banner up top and this
 *  zone must agree about read state, which two separate fetches cannot. */
export function ReviewZone({
  review,
  error,
  onRetry,
}: {
  review: WeeklyReviewRead | null | undefined;
  error: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations("tracker");

  const zoneSub = review
    ? `${review.week_start} · ${t("reviewGeneratedAt", { date: fmtTs(review.generated_at) })}`
    : undefined;

  return (
    <section className="w-full">
      <ZoneHead eyebrow={t("zoneEyebrowReview")} title={t("reviewTitle")} sub={zoneSub} />
      {review === undefined ? (
        error ? (
          <div className="rounded-lg border border-dashed p-4 text-center" style={{ borderColor: "var(--border)" }}>
            <p className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
            <Button size="sm" variant="outline" onClick={onRetry}>{t("retry")}</Button>
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
  // Reviews generated before V6 have no `days` key in their stored stats at
  // all. Pydantic fills the default on the way out, but the field is optional
  // in the schema for exactly that reason — so treat absent as "none recorded".
  const days = s.days ?? [];
  const benchPct = Math.round((s.benchmark_interview_rate ?? 0.08) * 100);

  return (
    <div className="rounded-lg border p-4 space-y-4" style={{ borderColor: "var(--border)" }}>
      {/* This-week triplet (week + generated time now live in the zone head) */}
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

      {/* Plan versus actual. Only days with a ritual record appear — a week
          zero-filled to seven bars would read as a week of failure rather than
          a week that was not planned. */}
      {days.length > 0 && (
        <div>
          <div className="text-2xs uppercase tracking-wide mb-1.5" style={{ color: "var(--ink-faint)" }}>
            {t("reviewDaysTitle")}
          </div>
          <div className="space-y-1.5">
            {days.map((d) => {
              const planned = d.committed_est ?? 0;
              const done = d.done_est ?? 0;
              // Scale to the busiest day of the week so the bars compare with
              // each other; an absolute scale would flatten a light week.
              const peak = Math.max(
                1,
                ...days.map((x) => Math.max(x.committed_est ?? 0, x.done_est ?? 0)),
              );
              return (
                <div key={d.date} className="flex items-center gap-2 text-2xs">
                  <span className="w-16 shrink-0 tabular-nums" style={{ color: "var(--ink-faint)" }}>
                    {d.date.slice(5)}
                  </span>
                  <div className="flex-1 min-w-0 space-y-0.5">
                    <div className="h-1.5 rounded-full" style={{ background: "var(--muted)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${(planned / peak) * 100}%`, background: "var(--ink-faint)" }}
                      />
                    </div>
                    <div className="h-1.5 rounded-full" style={{ background: "var(--muted)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${(done / peak) * 100}%`, background: "var(--primary)" }}
                      />
                    </div>
                  </div>
                  <span className="shrink-0 tabular-nums" style={{ color: "var(--ink-muted)" }}>
                    {/* Never "0" for a null. A day closed without a morning
                        ritual has committed_est null, and one planned but never
                        closed has done_est null — printing either as 0m would
                        collapse "no record" into "recorded nothing", which is
                        the distinction the whole feature is built around. */}
                    {t("reviewDayCommitted")}{" "}
                    {d.committed_est == null ? "—" : `${planned}m`} · {t("reviewDayDone")}{" "}
                    {d.done_est == null ? "—" : `${done}m`}
                  </span>
                </div>
              );
            })}
            {/* The reflections themselves, under the bars. They are the user's
                own words; showing them only to the model that summarises them
                would be an odd thing to do with someone's diary. */}
            {days.filter((d) => d.reflection).map((d) => (
              <p key={`${d.date}-r`} className="text-2xs pl-[4.5rem] italic" style={{ color: "var(--ink-muted)" }}>
                {d.date.slice(5)} — {d.reflection}
              </p>
            ))}
          </div>
        </div>
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
