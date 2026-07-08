import type { ElementType } from "react";
import { getTranslations } from "next-intl/server";
import type { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { listJobs, listRuns, getProfile, listFitReports } from "@/api/client";
import type { JobRead, RunRead, FitReportSummary } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { bandOf } from "@/lib/matchBand";
import { EmptyState } from "@/components/EmptyState";
import { Search, History, Building2 } from "lucide-react";
import { buttonVariants } from "@/components/ui/button-variants";
import { Metric } from "@/components/ui/metric";
import { rowClassName } from "@/components/ui/row";
import { cn } from "@/lib/utils";
import { MatchStatStrip, type TopPick } from "@/components/MatchStatStrip";

// Sidebar section header: icon + label + bottom border, so the four rail
// sections ("This search"/"Up next"/etc.) read as distinct blocks instead of
// four same-weight gray lines stacked with no separation.
function SidebarLabel({ icon: Icon, children }: { icon: ElementType; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 pb-2 mb-3" style={{ borderBottom: "1px solid var(--border)" }}>
      <Icon size={15} style={{ color: "var(--ink-muted)" }} />
      <span className="text-xs font-semibold" style={{ color: "var(--ink-primary)" }}>{children}</span>
    </div>
  );
}

export const dynamic = "force-dynamic";

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
  const topPicksData: TopPick[] = topPicks.map((job) => {
    const fr = fitMap.get(job.id);
    const score = fr?.overall_match_score;
    return {
      id: job.id,
      title: job.title,
      company: job.company,
      location: job.location,
      seniorityInferred: job.seniority_inferred,
      latestJobReportId: job.latest_job_report_id,
      score,
      whyPhrase: whyMatchPhrase(job, score),
      fitReport: fr
        ? { id: fr.id, score: fr.overall_match_score, recommended_next_action: fr.recommended_next_action }
        : undefined,
    };
  });

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
      {/* Content grid: main + right rail. No page-owned header bar here —
          the top bar (shared across all sections) already carries the
          "New Search" action; this page's identity comes from the hero
          copy below instead of a repeated title row. */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_220px] xl:grid-cols-[1fr_268px] overflow-y-auto lg:overflow-hidden">

        {/* Main content — deliberately NOT width-capped (no PageContainer):
            the right rail is a fixed-width column pinned to the grid's own
            edge, so letting this column fill the full 1fr track keeps the
            rail flush against it instead of leaving a growing gap between
            capped content and the rail on wide screens. */}
        <div className="lg:overflow-y-auto px-[var(--space-page-x)] py-[var(--space-page-y)]">

          {fetchError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-[var(--space-surface-compact)] text-sm text-rose-700 mb-5">
              {fetchError}
            </div>
          )}

          {/* Hero summary */}
          <div className="mb-[var(--space-stack-lg)]">
            <div className="flex items-center gap-[7px] mb-[var(--space-stack-xs)]">
              <div className="w-[7px] h-[7px] rounded-full" style={{ background: "var(--primary)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--primary)" }}>
                {lastSearchTime ? t("searchedAgo", { time: lastSearchTime }) : t("noSearchesYet")}
              </span>
            </div>
            <h1 className="text-2xl font-semibold mb-[var(--space-stack-xs)] leading-tight" style={{ color: "var(--ink-primary)" }}>
              {t("rolesFound", { count: total })}
            </h1>
            <p className="text-base leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
              {profileSummary ? t("basedOnProfile", { summary: truncatedSummary }) : t("setUpProfile")}
              {strongCount > 0 && ` ${t("strongMatchNote", { count: strongCount })}`}
            </p>
          </div>

          {/* Up next — the one clear call-to-action on this page, so it lives
              in the main column rather than the right rail: right-rail items
              are systematically under-noticed ("right-rail blindness"), and
              this is the single most actionable thing here. Kept compact
              (one row, same height as a rail item) so it doesn't compete
              with "Top picks" for attention. Uses the Row shape (border +
              padding scale) but keeps its own highlighted background —
              it's a deliberate CTA accent, not a neutral grouping. */}
          {unreviewedCount > 0 && (
            <Link
              href="/jobs?status=discovered"
              className={cn(rowClassName, "flex items-center gap-3 mb-[var(--space-stack-md)] transition-colors hover:opacity-90")}
              style={{ background: "var(--sidebar-item-active-bg)" }}
            >
              <Metric size="stat" style={{ color: "var(--primary)" }}>{unreviewedCount}</Metric>
              <span className="flex-1 text-sm" style={{ color: "var(--ink-secondary)" }}>
                {t("rolesToReviewLabel", { count: unreviewedCount })}
              </span>
              <span className="text-sm font-semibold whitespace-nowrap" style={{ color: "var(--primary)" }}>
                {t("reviewNow")} →
              </span>
            </Link>
          )}

          {/* Match stat strip + top picks */}
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
            <MatchStatStrip
              total={total}
              strongCount={strongCount}
              goodCount={goodCount}
              partialCount={partialCount}
              unanalyzedCount={unanalyzedCount}
              hasProfile={!!profileId}
              topPicks={topPicksData}
            />
          )}

          <div className="h-9" />
        </div>

        {/* Right rail */}
        <div
          className="lg:overflow-y-auto lg:min-h-0 bg-white px-5 py-6 flex flex-col gap-7 border-t lg:border-t-0 lg:border-l border-[var(--border)]"
        >
          {/* This search */}
          <div>
            <SidebarLabel icon={Search}>{t("thisSearch")}</SidebarLabel>
            <div
              className="rounded-lg p-[var(--space-rail-card-y)_var(--space-rail-card-x)]"
              style={{ background: "var(--background)", border: "1px solid oklch(88% 0.018 285)" }}
            >
              <div className="flex flex-col gap-2.5 mb-3.5">
                <div>
                  <div className="text-2xs mb-0.5" style={{ color: "var(--ink-muted)" }}>{t("profileLabel")}</div>
                  <div className="text-sm font-medium" style={{ color: "var(--ink-primary)" }}>
                    {truncatedSummary || t("notSetUp")}
                  </div>
                </div>
                <div>
                  <div className="text-2xs mb-0.5" style={{ color: "var(--ink-muted)" }}>{t("lastSearched")}</div>
                  <div className="text-sm" style={{ color: "var(--ink-secondary)" }}>
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
                      <span className="flex-1 text-sm" style={{ color: i === 0 ? "var(--ink-primary)" : "var(--ink-muted)" }}>
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
                    className="text-xs font-medium hover:underline"
                    style={{ color: "var(--primary)" }}
                  >
                    {t("viewAllSearches")}
                  </Link>
                </div>
              </>
            ) : (
              <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
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
                      className="text-xs truncate flex-1"
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
                    <span className="text-2xs w-4 text-right shrink-0 tabular-nums font-medium" style={{ color: "var(--ink-secondary)" }}>
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
