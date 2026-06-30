import Link from "next/link";
import { listJobs, listRuns, getProfile, listFitReports } from "@/api/client";
import type { JobRead, RunRead, FitReportSummary } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { fmtTs } from "@/lib/utils";
import { JobFitCell } from "@/app/jobs/JobFitCell";

export const dynamic = "force-dynamic";

function matchLabel(score: number | undefined): { text: string; style: "strong" | "good" | "partial" } {
  if (score === undefined) return { text: "New role", style: "partial" };
  if (score >= 75) return { text: "Strong match", style: "strong" };
  if (score >= 50) return { text: "Good fit", style: "good" };
  return { text: "Partial match", style: "partial" };
}

function matchBadgeClass(style: "strong" | "good" | "partial"): string {
  if (style === "strong") return "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]";
  if (style === "good") return "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]";
  return "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]";
}

function whyMatchText(job: JobRead, score: number | undefined): string | null {
  if (score === undefined) return null;
  const parts: string[] = [];
  if (job.primary_role_category && job.primary_role_category !== "unknown") {
    parts.push(job.primary_role_category.split(" / ")[0]);
  }
  if (job.seniority_inferred) {
    parts.push(`${job.seniority_inferred}-level`);
  }
  if (parts.length === 0) return null;
  return `${parts.join(", ")} role${job.location ? ` in ${job.location}` : ""} aligns with your profile.`;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}

// Backend caps `limit` at 500; Top picks/company-distribution need the full
// job set in memory to rank correctly, not just the most recently created page.
const FETCH_LIMIT = 500;

export default async function HomePage() {
  const token = await getServerToken();

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
  const strongCount = jobs.filter((j) => {
    const s = fitMap.get(j.id)?.overall_match_score;
    return s !== undefined && s >= 75;
  }).length;
  const goodCount = jobs.filter((j) => {
    const s = fitMap.get(j.id)?.overall_match_score;
    return s !== undefined && s >= 50 && s < 75;
  }).length;
  const partialCount = total - strongCount - goodCount;

  const discoveryRuns = runs
    .filter((r) => r.run_type === "job_discovery")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const lastSearch = discoveryRuns[0];
  const lastSearchTime = lastSearch ? relativeTime(lastSearch.created_at) : null;

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

  return (
    <>
      {/* Header bar */}
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          Role Inbox
        </span>
        <div className="flex-1" />
        <Link
          href="/workspace"
          className="flex items-center gap-[7px] h-[34px] px-[18px] rounded-lg text-[13px] font-semibold text-white shrink-0 transition-opacity hover:opacity-90"
          style={{ background: "var(--primary)", letterSpacing: "0.01em" }}
        >
          <svg width="11" height="11" viewBox="0 0 12 12">
            <line x1="6" y1="1" x2="6" y2="11" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            <line x1="1" y1="6" x2="11" y2="6" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          New Search
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
                {lastSearchTime ? `Searched ${lastSearchTime}` : "No searches yet"}
              </span>
            </div>
            <h2 className="text-[22px] font-semibold mb-[7px] leading-tight" style={{ color: "oklch(16% 0.015 275)" }}>
              {total} role{total !== 1 ? "s" : ""} found for you
            </h2>
            <p className="text-sm mb-[18px] leading-relaxed" style={{ color: "oklch(52% 0.01 275)" }}>
              {profileSummary
                ? `Based on your ${profileSummary.slice(0, 60).trim()}${profileSummary.length > 60 ? "…" : ""} profile.`
                : "Set up your profile to get personalized match scores."}
              {strongCount > 0 && ` ${strongCount} ${strongCount === 1 ? "is a" : "are"} strong match${strongCount !== 1 ? "es" : ""} — a good place to start reviewing.`}
            </p>
            <div className="flex gap-1.5 flex-wrap">
              <span className="py-[5px] px-3.5 rounded-full text-white text-[12.5px] font-medium" style={{ background: "oklch(20% 0.02 275)" }}>
                All · {total}
              </span>
              {strongCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-strong-bg)", color: "var(--match-strong-fg)", border: "1px solid var(--match-strong-border)" }}
                >
                  Strong · {strongCount}
                </span>
              )}
              {goodCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-good-bg)", color: "var(--match-good-fg)", border: "1px solid var(--match-good-border)" }}
                >
                  Good fit · {goodCount}
                </span>
              )}
              {partialCount > 0 && (
                <span
                  className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium"
                  style={{ background: "var(--match-partial-bg)", color: "var(--match-partial-fg)", border: "1px solid var(--match-partial-border)" }}
                >
                  Partial · {partialCount}
                </span>
              )}
            </div>
          </div>

          {/* Top picks */}
          {jobs.length === 0 && !fetchError ? (
            <div className="rounded-xl border border-dashed py-16 text-center" style={{ borderColor: "var(--border)" }}>
              <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>No roles in your inbox yet.</p>
              <Link
                href="/workspace"
                className="inline-flex items-center gap-1.5 mt-3 text-sm font-medium hover:underline"
                style={{ color: "var(--primary)" }}
              >
                Start your first search →
              </Link>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[12.5px] font-semibold" style={{ color: "oklch(38% 0.012 275)" }}>
                  {profileId ? "Top picks for you" : "Recent roles"}
                </span>
                {total > topPicks.length && (
                  <Link
                    href="/jobs"
                    className="text-[12.5px] font-medium hover:underline"
                    style={{ color: "var(--primary)" }}
                  >
                    View all {total} roles →
                  </Link>
                )}
              </div>
              <div className="flex flex-col gap-2.5">
              {topPicks.map((job) => {
                const fr = fitMap.get(job.id);
                const score = fr?.overall_match_score;
                const match = matchLabel(score);
                const isPartial = match.style === "partial";
                const why = whyMatchText(job, score);

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
                      <span className={`py-[3px] px-2.5 rounded text-xs font-medium ${matchBadgeClass(match.style)}`}>
                        {match.text}
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
                        style={{ color: isPartial ? "oklch(28% 0.012 275)" : "oklch(16% 0.015 275)" }}
                      >
                        {job.title}
                      </div>
                      <div className="text-[13px] mb-3.5" style={{ color: "oklch(56% 0.01 275)" }}>
                        {job.company}
                        {job.location && ` · ${job.location}`}
                        {job.seniority_inferred && ` · ${job.seniority_inferred}`}
                      </div>
                    </Link>

                    {/* Why this matches */}
                    {why && (
                      <div className="pt-3.5 flex items-start justify-between gap-5" style={{ borderTop: "1px solid oklch(93% 0.008 280)" }}>
                        <p className="text-[13px] leading-relaxed" style={{ color: "oklch(50% 0.01 275)" }}>
                          <span className="font-medium" style={{ color: isPartial ? "oklch(62% 0.01 275)" : "oklch(50% 0.2 285)" }}>
                            Why this matches —{" "}
                          </span>
                          {why}
                        </p>
                        <Link
                          href={`/jobs/${job.id}`}
                          className="text-[12.5px] font-medium whitespace-nowrap shrink-0 mt-[1px] hover:underline"
                          style={{ color: isPartial ? "oklch(62% 0.01 275)" : "var(--primary)" }}
                        >
                          View role →
                        </Link>
                      </div>
                    )}

                    {!why && (
                      <div className="pt-3.5 flex items-center justify-end" style={{ borderTop: "1px solid oklch(93% 0.008 280)" }}>
                        <Link
                          href={`/jobs/${job.id}`}
                          className="text-[12.5px] font-medium whitespace-nowrap hover:underline"
                          style={{ color: isPartial ? "oklch(62% 0.01 275)" : "var(--primary)" }}
                        >
                          View role →
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
            <div className="text-[12.5px] font-semibold mb-3" style={{ color: "oklch(38% 0.012 275)" }}>
              This search
            </div>
            <div
              className="rounded-lg p-[14px_16px]"
              style={{ background: "var(--background)", border: "1px solid oklch(88% 0.018 285)" }}
            >
              <div className="flex flex-col gap-2.5 mb-3.5">
                <div>
                  <div className="text-[11.5px] mb-0.5" style={{ color: "oklch(62% 0.01 275)" }}>Profile</div>
                  <div className="text-[13px] font-medium" style={{ color: "oklch(22% 0.015 275)" }}>
                    {profileSummary ? profileSummary.slice(0, 40).trim() + (profileSummary.length > 40 ? "…" : "") : "Not set up"}
                  </div>
                </div>
                <div>
                  <div className="text-[11.5px] mb-0.5" style={{ color: "oklch(62% 0.01 275)" }}>Last searched</div>
                  <div className="text-[13px]" style={{ color: "oklch(32% 0.012 275)" }}>
                    {lastSearchTime ?? "Never"}
                  </div>
                </div>
              </div>
              <Link
                href="/workspace"
                className="w-full h-8 flex items-center justify-center rounded-md text-[13px] font-medium text-white transition-opacity hover:opacity-90"
                style={{ background: "var(--primary)" }}
              >
                Search again
              </Link>
            </div>
          </div>

          {/* Up next */}
          <div>
            <div className="text-[12.5px] font-semibold mb-3" style={{ color: "oklch(38% 0.012 275)" }}>
              Up next
            </div>
            <div className="flex flex-col gap-2">
              {unreviewedCount > 0 && (
                <Link
                  href="/jobs?status=discovered"
                  className="flex items-center gap-2.5 p-[11px_14px] rounded-lg transition-colors hover:opacity-90"
                  style={{ background: "var(--sidebar-item-active-bg)" }}
                >
                  <div className="w-[7px] h-[7px] rounded-full shrink-0" style={{ background: "var(--primary)" }} />
                  <span className="flex-1 text-[13px] font-medium" style={{ color: "oklch(36% 0.015 275)" }}>
                    {unreviewedCount} role{unreviewedCount !== 1 ? "s" : ""} to review
                  </span>
                  <span className="text-[13px]" style={{ color: "var(--primary)" }}>→</span>
                </Link>
              )}
              <Link
                href="/workspace"
                className="flex items-center gap-2.5 p-[11px_14px] rounded-lg transition-colors hover:bg-zinc-50"
                style={{ border: "1px solid var(--border)" }}
              >
                <div className="w-[7px] h-[7px] rounded-full shrink-0" style={{ background: "oklch(86% 0.01 275)" }} />
                <span className="flex-1 text-[13px]" style={{ color: "oklch(48% 0.01 275)" }}>
                  Start new search
                </span>
                <span className="text-[13px]" style={{ color: "oklch(64% 0.01 275)" }}>→</span>
              </Link>
            </div>
          </div>

          {/* Recent searches */}
          <div>
            <div className="text-[12.5px] font-semibold mb-3" style={{ color: "oklch(38% 0.012 275)" }}>
              Recent searches
            </div>
            {recentSearches.length > 0 ? (
              <>
                <div className="flex flex-col">
                  {recentSearches.map((run, i) => (
                    <Link
                      key={run.id}
                      href={run.status === "succeeded" ? "/" : `/runs/${run.id}`}
                      className="flex items-center py-[9px] hover:opacity-80"
                      style={{
                        borderBottom: i < recentSearches.length - 1 ? "1px solid oklch(93% 0.008 280)" : undefined,
                      }}
                    >
                      <span className="flex-1 text-[13px]" style={{ color: i === 0 ? "oklch(30% 0.015 275)" : "oklch(48% 0.01 275)" }}>
                        Discovery Run
                      </span>
                      <span className="text-xs" style={{ color: "oklch(66% 0.008 275)" }}>
                        {relativeTime(run.created_at)}
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
                    View all searches →
                  </Link>
                </div>
              </>
            ) : (
              <p className="text-[13px]" style={{ color: "oklch(60% 0.01 275)" }}>
                No searches yet.
              </p>
            )}
          </div>

          {/* Top companies */}
          {topCompanies.length > 0 && (
            <div>
              <div className="text-[12.5px] font-semibold mb-3" style={{ color: "oklch(38% 0.012 275)" }}>
                Top companies
              </div>
              <div className="flex flex-col gap-2">
                {topCompanies.map(([company, count]) => (
                  <div key={company} className="flex items-center gap-2.5">
                    <span
                      className="text-[12.5px] truncate flex-1"
                      style={{ color: "oklch(36% 0.012 275)" }}
                      title={company}
                    >
                      {company}
                    </span>
                    <div className="w-16 h-1.5 rounded-full shrink-0" style={{ background: "oklch(94% 0.01 275)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${(count / maxCompanyCount) * 100}%`, background: "var(--primary)" }}
                      />
                    </div>
                    <span className="text-[11.5px] w-4 text-right shrink-0" style={{ color: "oklch(56% 0.01 275)" }}>
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
