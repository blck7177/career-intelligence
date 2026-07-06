import type { ElementType } from "react";
import { getTranslations } from "next-intl/server";
import type { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { listJobs, listRuns, getProfile, listFitReports } from "@/api/client";
import type { JobRead, RunRead, FitReportSummary } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { JobFitCell } from "@/app/[locale]/jobs/JobFitCell";
import { bandOf, BAND } from "@/lib/matchBand";
import { CompositionBar } from "@/components/CompositionBar";
import { EmptyState } from "@/components/EmptyState";
import { Search, Compass, History, Building2 } from "lucide-react";
import { buttonVariants } from "@/components/ui/button-variants";

// Sidebar section header: icon + label + bottom border, so the four rail
// sections ("This search"/"Up next"/etc.) read as distinct blocks instead of
// four same-weight gray lines stacked with no separation.
function SidebarLabel({ icon: Icon, children }: { icon: ElementType; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 pb-2 mb-3" style={{ borderBottom: "1px solid var(--border)" }}>
      <Icon size={13} style={{ color: "var(--ink-muted)" }} />
      <span className="text-[12.5px] font-semibold" style={{ color: "var(--ink-primary)" }}>{children}</span>
    </div>
  );
}

export const dynamic = "force-dynamic";

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

function matchBadgeStyle(score: number | undefined): { backgroundColor: string; color: string } | undefined {
  if (score === undefined) return undefined;
  const b = BAND[bandOf(score)];
  return { backgroundColor: b.bg, color: b.fg };
}

function whyMatchPhrase(job: JobRead, score: number | undefined): string | null {
  if (score === undefined) return null;
  const parts: string[] = [];
  if (job.primary_role_category && job.primary_role_category !== "unknown") {
    parts.push(job.primary_role_category.split(" / ")[0]);
  }
  if (job.seniority_inferred) {
    parts.push(`${job.seniority_inferred}-level`);
  }
  if (parts.length === 0) return null;
  return `${parts.join(", ")} role${job.location ? ` in ${job.location}` : ""}`;
}

type TCommon = ReturnType<typeof useTranslations>;

function relativeTime(iso: string, t: TCommon): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return t("minutesAgo", { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t("hoursAgo", { count: hrs });
  const days = Math.floor(hrs / 24);
  if (days === 1) return t("yesterday");
  return t("daysAgo", { count: days });
}

// Backend caps `limit` at 500; Top picks/company-distribution need the full
// job set in memory to rank correctly, not just the most recently created page.
const FETCH_LIMIT = 500;

export default async function HomePage() {
  const token = await getServerToken();
  const t = await getTranslations("home");
  const tCommon = await getTranslations("common");

  let jobs: JobRead[] = [];
  let runs: RunRead[] = [];
  let profileSummary = "";
  let profileId: string | undefined;
  let fetchError: string | null = null;

  try {
    const [jobList, runList, profile] = await Promise.all([
      listJobs({ include_report_summary: true, limit: FETCH_LIMIT }, token),
      listRuns(token).catch(() => ({ items: [] as RunRead[] })),
      getProfile(token).catch(() => null),
    ]);
    jobs = jobList.items;
    runs = runList.items;
    profileSummary = profile?.summary ?? "";
    profileId = profile?.id;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load data";
  }

  const fitListData = profileId
    ? await listFitReports({ profile_id: profileId }, token).catch(() => ({
        items: [] as FitReportSummary[],
        total: 0,
      }))
    : { items: [] as FitReportSummary[], total: 0 };

  const fitMap = new Map<string, FitReportSummary>();
  for (const fr of fitListData.items) {
    if (!fitMap.has(fr.job_id)) {
      fitMap.set(fr.job_id, fr);
    }
  }

  if (profileId && fitMap.size > 0) {
    jobs = [...jobs].sort((a, b) => {
      const sa = fitMap.get(a.id)?.overall_match_score ?? -1;
      const sb = fitMap.get(b.id)?.overall_match_score ?? -1;
      return sb - sa;
    });
  }

  const total = jobs.length;
  const analyzedBands = jobs
    .map((j) => fitMap.get(j.id)?.overall_match_score)
    .filter((s): s is number => s !== undefined)
    .map(bandOf);
  const strongCount = analyzedBands.filter((b) => b === "strong").length;
  const goodCount = analyzedBands.filter((b) => b === "partial").length;
  const partialCount = analyzedBands.filter((b) => b === "gaps").length;
  const unanalyzedCount = total - strongCount - goodCount - partialCount;

  const discoveryRuns = runs
    .filter((r) => r.run_type === "job_discovery")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const lastSearch = discoveryRuns[0];
  const lastSearchTime = lastSearch ? relativeTime(lastSearch.created_at, tCommon) : null;

  const unreviewedCount = jobs.filter((j) => j.status === "discovered").length;
  const recentSearches = discoveryRuns.slice(0, 3);

  const TOP_PICKS_COUNT = 8;
  const topPicks = jobs.slice(0, TOP_PICKS_COUNT);

  const companyCounts = new Map<string, number>();
  for (const j of jobs) {
    companyCounts.set(j.company, (companyCounts.get(j.company) ?? 0) + 1);
  }
  const topCompanies = [...companyCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  const maxCompanyCount = topCompanies[0]?.[1] ?? 1;

  const truncatedSummary = profileSummary
    ? profileSummary.slice(0, 60).trim() + (profileSummary.length > 60 ? "…" : "")
    : "";

  return (
    <>
      {/* Header bar */}
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          {t("title")}
        </span>
        <div className="flex-1" />
        <Link
          href="/workspace"
          className={buttonVariants({ className: "shrink-0 gap-[7px]" })}
          style={{ letterSpacing: "0.01em" }}
        >
          <svg width="11" height="11" viewBox="0 0 12 12">
            <line x1="6" y1="1" x2="6" y2="11" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            <line x1="1" y1="6" x2="11" y2="6" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {t("newSearch")}
        </Link>
      </header>

      {/* Content grid: main + right rail */}
      <div className="flex-1 min-h-0 grid grid-cols-[1fr_268px] overflow-hidden">

        {/* Main content */}
        <div className="overflow-y-auto px-7 py-6">

          {fetchError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 mb-5">
              {fetchError}
            </div>
          )}

          {/* Hero summary */}
          <div
            className="bg-white rounded-xl p-[22px_26px] mb-5"
            style={{
              border: "1px solid oklch(86% 0.022 285)",
              boxShadow: "0 2px 10px oklch(52% 0.15 285 / 0.07)",
            }}
          >
            <div className="flex items-center gap-[7px] mb-2.5">
              <div className="w-[7px] h-[7px] rounded-full" style={{ background: "var(--primary)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--primary)" }}>
                {lastSearchTime ? t("searchedAgo", { time: lastSearchTime }) : t("noSearchesYet")}
              </span>
            </div>
            <h2 className="text-[22px] font-semibold mb-[7px] leading-tight" style={{ color: "var(--ink-primary)" }}>
              {t("rolesFound", { count: total })}
            </h2>
            <p className="text-sm mb-[18px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
              {profileSummary ? t("basedOnProfile", { summary: truncatedSummary }) : t("setUpProfile")}
              {strongCount > 0 && ` ${t("strongMatchNote", { count: strongCount })}`}
            </p>
            <div className="flex gap-1.5 flex-wrap">
              <span className="py-[5px] px-3.5 rounded-full text-white text-[12.5px] font-medium" style={{ background: "var(--ink-primary)" }}>
                {t("filterAll", { count: total })}
              </span>
              {strongCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-strong-bg)", color: "var(--match-strong-fg)", border: "1px solid var(--match-strong-border)" }}
                >
                  {t("filterStrong", { count: strongCount })}
                </span>
              )}
              {goodCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-good-bg)", color: "var(--match-good-fg)", border: "1px solid var(--match-good-border)" }}
                >
                  {t("filterGood", { count: goodCount })}
                </span>
              )}
              {partialCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-partial-bg)", color: "var(--match-partial-fg)", border: "1px solid var(--match-partial-border)" }}
                >
                  {t("filterPartial", { count: partialCount })}
                </span>
              )}
              {unanalyzedCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--muted)", color: "var(--muted-foreground)", border: "1px solid var(--border)" }}
                >
                  {t("filterUnanalyzed", { count: unanalyzedCount })}
                </span>
              )}
            </div>
            {total > 0 && (
              <CompositionBar
                className="mt-4"
                ariaLabel={t("matchDistribution")}
                segments={[
                  { key: "strong", count: strongCount, label: t("matchStrong"), color: BAND.strong.ring },
                  { key: "good", count: goodCount, label: t("matchGood"), color: BAND.partial.ring },
                  { key: "partial", count: partialCount, label: t("matchPartial"), color: BAND.gaps.ring },
                  { key: "unanalyzed", count: unanalyzedCount, label: t("matchUnanalyzedLabel"), color: "var(--ink-faint)" },
                ]}
              />
            )}
          </div>

          {/* Top picks */}
          {jobs.length === 0 && !fetchError ? (
            <EmptyState
              icon={Search}
              title={t("emptyState")}
              action={
                <Link
                  href="/workspace"
                  className="inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  {t("startFirstSearch")}
                </Link>
              }
            />
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[12.5px] font-semibold" style={{ color: "var(--ink-primary)" }}>
                  {profileId ? t("topPicksForYou") : t("recentRoles")}
                </span>
                {total > topPicks.length && (
                  <Link
                    href="/jobs"
                    className="text-[12.5px] font-medium hover:underline"
                    style={{ color: "var(--primary)" }}
                  >
                    {t("viewAllRoles", { count: total })}
                  </Link>
                )}
              </div>
              <div className="flex flex-col gap-2.5">
              {topPicks.map((job) => {
                const fr = fitMap.get(job.id);
                const score = fr?.overall_match_score;
                const band = score !== undefined ? bandOf(score) : undefined;
                const isPartial = band === "gaps" || band === undefined;
                const whyPhrase = whyMatchPhrase(job, score);
                const why = whyPhrase ? t("matchesProfile", { phrase: whyPhrase }) : null;

                return (
                  <div
                    key={job.id}
                    className="bg-white rounded-[10px] p-[20px_22px] transition-shadow hover:shadow-md"
                    style={{
                      border: "1px solid var(--border)",
                      boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)",
                      opacity: isPartial ? 0.88 : 1,
                    }}
                  >
                    {/* Top row: badge + actions */}
                    <div className="flex items-center gap-2.5 mb-3">
                      <span
                        className={`py-[3px] px-2.5 rounded text-xs font-medium ${score === undefined ? "bg-[var(--muted)] text-[var(--ink-muted)]" : ""}`}
                        style={matchBadgeStyle(score)}
                      >
                        {t(matchKey(score))}
                      </span>
                      <div className="flex-1" />
                      <div className="flex items-center gap-2 shrink-0">
                        <JobFitCell
                          jobId={job.id}
                          jobReportId={job.latest_job_report_id}
                          hasProfile={!!profileId}
                          fitReport={
                            fr
                              ? {
                                  id: fr.id,
                                  score: fr.overall_match_score,
                                  recommended_next_action: fr.recommended_next_action,
                                }
                              : undefined
                          }
                        />
                      </div>
                    </div>

                    {/* Title + company */}
                    <Link href={`/jobs/${job.id}`} className="block group">
                      <div
                        className="text-base font-semibold mb-1 group-hover:underline"
                        style={{ color: isPartial ? "var(--ink-secondary)" : "var(--ink-primary)" }}
                      >
                        {job.title}
                      </div>
                      <div className="text-[13px] mb-3.5" style={{ color: "var(--ink-muted)" }}>
                        {job.company}
                        {job.location && ` · ${job.location}`}
                        {job.seniority_inferred && ` · ${job.seniority_inferred}`}
                      </div>
                    </Link>

                    {/* Why this matches */}
                    {why && (
                      <div className="pt-3.5 flex items-start justify-between gap-5" style={{ borderTop: "1px solid var(--border)" }}>
                        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
                          <span className="font-medium" style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}>
                            {t("whyThisMatches")}
                          </span>
                          {why}
                        </p>
                        <Link
                          href={`/jobs/${job.id}`}
                          className="text-[12.5px] font-medium whitespace-nowrap shrink-0 mt-[1px] hover:underline"
                          style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}
                        >
                          {tCommon("viewRole")}
                        </Link>
                      </div>
                    )}

                    {!why && (
                      <div className="pt-3.5 flex items-center justify-end" style={{ borderTop: "1px solid var(--border)" }}>
                        <Link
                          href={`/jobs/${job.id}`}
                          className="text-[12.5px] font-medium whitespace-nowrap hover:underline"
                          style={{ color: isPartial ? "var(--ink-muted)" : "var(--primary)" }}
                        >
                          {tCommon("viewRole")}
                        </Link>
                      </div>
                    )}
                  </div>
                );
              })}
              </div>
            </>
          )}

          <div className="h-9" />
        </div>

        {/* Right rail */}
        <div
          className="overflow-y-auto min-h-0 bg-white px-5 py-6 flex flex-col gap-7"
          style={{ borderLeft: "1px solid var(--border)" }}
        >
          {/* This search */}
          <div>
            <SidebarLabel icon={Search}>{t("thisSearch")}</SidebarLabel>
            <div
              className="rounded-lg p-[14px_16px]"
              style={{ background: "var(--background)", border: "1px solid oklch(88% 0.018 285)" }}
            >
              <div className="flex flex-col gap-2.5 mb-3.5">
                <div>
                  <div className="text-[11.5px] mb-0.5" style={{ color: "var(--ink-muted)" }}>{t("profileLabel")}</div>
                  <div className="text-[13px] font-medium" style={{ color: "var(--ink-primary)" }}>
                    {truncatedSummary || t("notSetUp")}
                  </div>
                </div>
                <div>
                  <div className="text-[11.5px] mb-0.5" style={{ color: "var(--ink-muted)" }}>{t("lastSearched")}</div>
                  <div className="text-[13px]" style={{ color: "var(--ink-secondary)" }}>
                    {lastSearchTime ?? tCommon("never")}
                  </div>
                </div>
              </div>
              <Link
                href="/workspace"
                className={buttonVariants({ size: "sm", className: "w-full" })}
              >
                {t("searchAgain")}
              </Link>
            </div>
          </div>

          {/* Up next */}
          <div>
            <SidebarLabel icon={Compass}>{t("upNext")}</SidebarLabel>
            <div className="flex flex-col gap-2">
              {unreviewedCount > 0 && (
                <Link
                  href="/jobs?status=discovered"
                  className="flex items-center gap-2.5 p-[11px_14px] rounded-lg transition-colors hover:opacity-90"
                  style={{ background: "var(--sidebar-item-active-bg)" }}
                >
                  <div className="w-[7px] h-[7px] rounded-full shrink-0" style={{ background: "var(--primary)" }} />
                  <span className="flex-1 text-[13px] font-medium" style={{ color: "var(--ink-primary)" }}>
                    {t("rolesToReview", { count: unreviewedCount })}
                  </span>
                  <span className="text-[13px]" style={{ color: "var(--primary)" }}>→</span>
                </Link>
              )}
              <Link
                href="/workspace"
                className="flex items-center gap-2.5 p-[11px_14px] rounded-lg transition-colors hover:bg-[var(--muted)]"
                style={{ border: "1px solid var(--border)" }}
              >
                <div className="w-[7px] h-[7px] rounded-full shrink-0" style={{ background: "var(--border)" }} />
                <span className="flex-1 text-[13px]" style={{ color: "var(--ink-secondary)" }}>
                  {t("startNewSearch")}
                </span>
                <span className="text-[13px]" style={{ color: "var(--ink-faint)" }}>→</span>
              </Link>
            </div>
          </div>

          {/* Recent searches */}
          <div>
            <SidebarLabel icon={History}>{t("recentSearches")}</SidebarLabel>
            {recentSearches.length > 0 ? (
              <>
                <div className="flex flex-col">
                  {recentSearches.map((run, i) => (
                    <Link
                      key={run.id}
                      href={run.status === "succeeded" ? "/" : `/runs/${run.id}`}
                      className="flex items-center py-[9px] hover:opacity-80"
                      style={{
                        borderBottom: i < recentSearches.length - 1 ? "1px solid var(--border)" : undefined,
                      }}
                    >
                      <span className="flex-1 text-[13px]" style={{ color: i === 0 ? "var(--ink-primary)" : "var(--ink-muted)" }}>
                        {t("discoveryRun")}
                      </span>
                      <span className="text-xs" style={{ color: "var(--ink-faint)" }}>
                        {relativeTime(run.created_at, tCommon)}
                      </span>
                    </Link>
                  ))}
                </div>
                <div className="mt-3">
                  <Link
                    href="/runs"
                    className="text-[12.5px] font-medium hover:underline"
                    style={{ color: "var(--primary)" }}
                  >
                    {t("viewAllSearches")}
                  </Link>
                </div>
              </>
            ) : (
              <p className="text-[13px]" style={{ color: "var(--ink-muted)" }}>
                {t("noSearchesPeriod")}
              </p>
            )}
          </div>

          {/* Top companies */}
          {topCompanies.length > 0 && (
            <div>
              <SidebarLabel icon={Building2}>{t("topCompanies")}</SidebarLabel>
              <div className="flex flex-col gap-2">
                {topCompanies.map(([company, count]) => (
                  <div key={company} className="flex items-center gap-2.5 group" title={`${company}: ${count}`}>
                    <span
                      className="text-[12.5px] truncate flex-1"
                      style={{ color: "var(--ink-secondary)" }}
                    >
                      {company}
                    </span>
                    <div className="w-16 h-1.5 rounded-full shrink-0" style={{ background: "var(--muted)" }}>
                      <div
                        className="h-full rounded-full transition-[width] duration-500 group-hover:opacity-80"
                        style={{ width: `${(count / maxCompanyCount) * 100}%`, background: "var(--primary)" }}
                      />
                    </div>
                    <span className="text-[11.5px] w-4 text-right shrink-0 tabular-nums font-medium" style={{ color: "var(--ink-secondary)" }}>
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
