"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { bandOf, BAND } from "@/lib/matchBand";
import { JobFitCell } from "@/app/[locale]/jobs/JobFitCell";
import { Metric } from "@/components/ui/metric";

type Filter = "all" | "strong" | "good" | "partial" | "unanalyzed";
type MatchKey = "matchNewRole" | "matchStrong" | "matchGood" | "matchPartial";

// "strong"/"partial"/"gaps" bands map onto this page's existing matchStrong/
// matchGood/matchPartial copy — same 70/50 thresholds as the rest of the app.
function matchKey(score: number | undefined): MatchKey {
  if (score === undefined) return "matchNewRole";
  const band = bandOf(score);
  if (band === "strong") return "matchStrong";
  if (band === "partial") return "matchGood";
  return "matchPartial";
}

function filterOf(score: number | undefined): Filter {
  if (score === undefined) return "unanalyzed";
  const band = bandOf(score);
  if (band === "strong") return "strong";
  if (band === "partial") return "good";
  return "partial";
}

function matchBadgeStyle(score: number | undefined): { backgroundColor: string; color: string } | undefined {
  if (score === undefined) return undefined;
  const b = BAND[bandOf(score)];
  return { backgroundColor: b.bg, color: b.fg };
}

export interface TopPick {
  id: string;
  title: string;
  company: string;
  location?: string | null;
  seniorityInferred?: string | null;
  latestJobReportId?: string | null;
  score?: number;
  whyPhrase: string | null;
  fitReport?: { id: string; score: number; recommended_next_action?: string | null };
}

interface StatTabDef {
  key: Filter;
  count: number;
  labelKey: "statAll" | "statStrong" | "statGood" | "statPartial" | "statUnanalyzed";
  ring?: string;
}

interface MatchStatStripProps {
  total: number;
  strongCount: number;
  goodCount: number;
  partialCount: number;
  unanalyzedCount: number;
  hasProfile: boolean;
  topPicks: TopPick[];
}

/**
 * Big-number filter strip — replaces the old row of count pills + a separate
 * CompositionBar. Each tab is both the count display *and* the filter
 * control (client-side, over the already-fetched topPicks slice — this is a
 * "top picks" preview, not the full role list, so a filter can show fewer
 * than its own count if some matching roles rank outside the preview; the
 * full filtered set is always still reachable via "View all roles").
 */
export function MatchStatStrip({
  total,
  strongCount,
  goodCount,
  partialCount,
  unanalyzedCount,
  hasProfile,
  topPicks,
}: MatchStatStripProps) {
  const t = useTranslations("home");
  const tCommon = useTranslations("common");
  const [filter, setFilter] = useState<Filter>("all");

  const tabs: StatTabDef[] = [
    { key: "all", count: total, labelKey: "statAll" },
    { key: "strong", count: strongCount, labelKey: "statStrong", ring: BAND.strong.ring },
    { key: "good", count: goodCount, labelKey: "statGood", ring: BAND.partial.ring },
    { key: "partial", count: partialCount, labelKey: "statPartial", ring: BAND.gaps.ring },
    { key: "unanalyzed", count: unanalyzedCount, labelKey: "statUnanalyzed" },
  ];

  const visiblePicks = filter === "all" ? topPicks : topPicks.filter((p) => filterOf(p.score) === filter);

  return (
    <>
      <div
        className="grid mb-[var(--space-stack-md)] rounded-xl overflow-hidden bg-white"
        style={{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)`, border: "1px solid var(--border)", boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)" }}
      >
        {tabs.map((tab, i) => {
          const active = filter === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setFilter(tab.key)}
              className="relative flex flex-col items-start gap-0.5 px-4 py-3.5 text-left transition-colors hover:bg-[var(--muted)]"
              style={{
                background: active ? "var(--muted)" : undefined,
                borderRight: i < tabs.length - 1 ? "1px solid var(--border)" : undefined,
              }}
            >
              <Metric
                size="stat"
                style={{ color: tab.ring ?? (active ? "var(--ink-primary)" : "var(--ink-faint)"), filter: active ? "saturate(1.15)" : undefined }}
              >
                {tab.count}
              </Metric>
              <span
                className="text-2xs font-semibold uppercase tracking-wide"
                style={{ color: active ? "var(--ink-primary)" : "var(--ink-muted)" }}
              >
                {t(tab.labelKey)}
              </span>
              <span
                className="absolute left-0 right-0 -bottom-px h-[3px] rounded-t-full transition-opacity"
                style={{ background: tab.ring ?? "var(--primary)", opacity: active ? 1 : 0 }}
              />
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between mb-[var(--space-stack-sm)]">
        <span className="text-xs font-semibold" style={{ color: "var(--ink-primary)" }}>
          {hasProfile ? t("topPicksForYou") : t("recentRoles")}
        </span>
        {total > topPicks.length && (
          <Link href="/jobs" className="text-xs font-medium hover:underline" style={{ color: "var(--primary)" }}>
            {t("viewAllRoles", { count: total })}
          </Link>
        )}
      </div>

      <div className="flex flex-col gap-[var(--space-stack-sm)]">
        {visiblePicks.map((job) => {
          const isPartial = filterOf(job.score) === "partial" || filterOf(job.score) === "unanalyzed";
          const why = job.whyPhrase ? t("matchesProfile", { phrase: job.whyPhrase }) : null;

          return (
            <div
              key={job.id}
              className="bg-white rounded-[10px] p-[var(--space-row-card-y)_var(--space-row-card-x)] transition-shadow hover:shadow-md"
              style={{ border: "1px solid var(--border)", boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)", opacity: isPartial ? 0.88 : 1 }}
            >
              <div className="flex items-center gap-2.5 mb-3">
                <span
                  className={`py-[3px] px-2.5 rounded text-xs font-medium ${job.score === undefined ? "bg-[var(--muted)] text-[var(--ink-muted)]" : ""}`}
                  style={matchBadgeStyle(job.score)}
                >
                  {t(matchKey(job.score))}
                </span>
                <div className="flex-1" />
                <div className="flex items-center gap-2 shrink-0">
                  <JobFitCell
                    jobId={job.id}
                    jobReportId={job.latestJobReportId}
                    hasProfile={hasProfile}
                    fitReport={job.fitReport}
                  />
                </div>
              </div>

              <Link href={`/jobs/${job.id}`} className="block group">
                <div
                  className="text-lg font-semibold mb-1 group-hover:underline"
                  style={{ color: isPartial ? "var(--ink-secondary)" : "var(--ink-primary)" }}
                >
                  {job.title}
                </div>
                <div className="text-sm mb-3.5" style={{ color: "var(--ink-muted)" }}>
                  {job.company}
                  {job.location && ` · ${job.location}`}
                  {job.seniorityInferred && ` · ${job.seniorityInferred}`}
                </div>
              </Link>

              {why ? (
                <div className="pt-3.5 flex items-start justify-between gap-5" style={{ borderTop: "1px solid var(--border)" }}>
                  <p className="text-sm leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
                    <span className="font-medium" style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}>
                      {t("whyThisMatches")}
                    </span>
                    {why}
                  </p>
                  <Link
                    href={`/jobs/${job.id}`}
                    className="text-xs font-medium whitespace-nowrap shrink-0 mt-[1px] hover:underline"
                    style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}
                  >
                    {tCommon("viewRole")}
                  </Link>
                </div>
              ) : (
                <div className="pt-3.5 flex items-center justify-end" style={{ borderTop: "1px solid var(--border)" }}>
                  <Link
                    href={`/jobs/${job.id}`}
                    className="text-xs font-medium whitespace-nowrap hover:underline"
                    style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}
                  >
                    {tCommon("viewRole")}
                  </Link>
                </div>
              )}
            </div>
          );
        })}

        {visiblePicks.length === 0 && (
          <p className="text-sm py-6 text-center" style={{ color: "var(--ink-muted)" }}>
            {t("emptyFilterNote")}
          </p>
        )}
      </div>
    </>
  );
}
