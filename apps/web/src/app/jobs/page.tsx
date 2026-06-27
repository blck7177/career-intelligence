import Link from "next/link";
import { Suspense } from "react";
import { listJobs, listFitReports, getProfile } from "@/api/client";
import type { FitReportSummary, JobRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { fmtTs } from "@/lib/utils";
import { ArchiveJobButton } from "./ArchiveJobButton";
import { JobFilters } from "./JobFilters";
import { JobFitCell } from "./JobFitCell";

export const dynamic = "force-dynamic";

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";

interface PageProps {
  searchParams: Promise<{
    profile_id?: string;
    role_category?: string;
    seniority?: string;
    confidence?: string;
    status?: string;
    q?: string;
    sort?: string;
  }>;
}

const SAVED_VIEWS: { label: string; status: StatusFilter }[] = [
  { label: "All", status: "all" },
  { label: "Report Ready", status: "reportable" },
  { label: "Needs Report", status: "discovered" },
  { label: "Stale", status: "stale" },
];

function matchStyle(score: number | undefined): "strong" | "good" | "partial" {
  if (score === undefined) return "partial";
  if (score >= 75) return "strong";
  if (score >= 50) return "good";
  return "partial";
}

function matchBadge(style: "strong" | "good" | "partial"): { text: string; classes: string } {
  if (style === "strong")
    return { text: "Strong match", classes: "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]" };
  if (style === "good")
    return { text: "Good fit", classes: "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]" };
  return { text: "Partial", classes: "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]" };
}

function uniqueRoleCategories(jobs: JobRead[]): string[] {
  const set = new Set<string>();
  for (const j of jobs) {
    if (j.primary_role_category && j.primary_role_category !== "unknown") {
      set.add(j.primary_role_category);
    }
  }
  return [...set].sort();
}

function buildQuery(
  params: Record<string, string | undefined>,
  overrides: Record<string, string | undefined>,
): string {
  const merged = { ...params, ...overrides };
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(merged)) {
    if (v) qs.set(k, v);
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export default async function JobsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const token = await getServerToken();

  const statusFilter = (params.status as StatusFilter) || "all";
  const profileId = params.profile_id;

  const [jobList, profile] = await Promise.all([
    listJobs(
      {
        status: statusFilter !== "all" ? statusFilter : undefined,
        include_report_summary: true,
      },
      token,
    ).catch(() => ({ items: [] as JobRead[], total: 0 })),
    getProfile(token).catch(() => null),
  ]);

  const resolvedProfileId = profileId ?? profile?.id;
  const fitListData = resolvedProfileId
    ? await listFitReports({ profile_id: resolvedProfileId }, token).catch(() => ({
        items: [] as FitReportSummary[],
        total: 0,
      }))
    : { items: [] as FitReportSummary[], total: 0 };

  let jobs = jobList.items;

  if (params.role_category) {
    jobs = jobs.filter((j) => j.primary_role_category === params.role_category);
  }
  if (params.seniority) {
    const term = params.seniority.toLowerCase();
    jobs = jobs.filter((j) => j.seniority_inferred?.toLowerCase().includes(term));
  }
  if (params.confidence) {
    jobs = jobs.filter((j) => j.role_category_confidence === params.confidence);
  }
  if (params.q) {
    const q = params.q.toLowerCase();
    jobs = jobs.filter(
      (j) =>
        j.title.toLowerCase().includes(q) ||
        j.company.toLowerCase().includes(q) ||
        (j.location?.toLowerCase().includes(q) ?? false),
    );
  }

  const fitMap = new Map<string, FitReportSummary>();
  for (const fr of fitListData.items) {
    if (!fitMap.has(fr.job_id)) {
      fitMap.set(fr.job_id, fr);
    }
  }

  const activeProfileId = resolvedProfileId;

  if (activeProfileId) {
    jobs = [...jobs].sort((a, b) => {
      const sa = fitMap.get(a.id)?.overall_match_score ?? -1;
      const sb = fitMap.get(b.id)?.overall_match_score ?? -1;
      return sb - sa;
    });
  } else if (params.sort === "oldest") {
    jobs = [...jobs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  } else if (params.sort === "company") {
    jobs = [...jobs].sort((a, b) => a.company.localeCompare(b.company));
  }

  const roleCategories = uniqueRoleCategories(jobList.items);
  const profileOptions = profile
    ? [{ id: profile.id, label: profile.summary?.slice(0, 40) ?? "Your Profile" }]
    : [];

  const activeFilters = [
    params.profile_id,
    params.role_category,
    params.seniority,
    params.confidence,
    params.q,
  ].filter(Boolean).length;

  return (
    <>
      {/* Header */}
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          Saved Roles
        </span>
        <span className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          {jobs.length} role{jobs.length !== 1 ? "s" : ""}
          {activeProfileId && fitMap.size > 0 && " · sorted by fit"}
          {activeFilters > 0 && ` · ${activeFilters} filter${activeFilters !== 1 ? "s" : ""}`}
        </span>
        <div className="flex-1" />
        <Link
          href="/workspace"
          className="flex items-center gap-[7px] h-[34px] px-[18px] rounded-lg text-[13px] font-semibold text-white shrink-0 transition-opacity hover:opacity-90"
          style={{ background: "var(--primary)" }}
        >
          <svg width="11" height="11" viewBox="0 0 12 12">
            <line x1="6" y1="1" x2="6" y2="11" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
            <line x1="1" y1="6" x2="11" y2="6" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          New Search
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto px-7 py-6">
        {/* Status filter pills */}
        <div className="flex flex-wrap gap-1.5 mb-5">
          {SAVED_VIEWS.map(({ label, status }) => {
            const active = statusFilter === status;
            return (
              <Link
                key={status}
                href={`/jobs${buildQuery(params, { status: status === "all" ? undefined : status })}`}
                className="py-[5px] px-3.5 rounded-full text-[12.5px] font-medium transition-colors"
                style={
                  active
                    ? { background: "oklch(20% 0.02 275)", color: "#fff" }
                    : { background: "var(--muted)", color: "var(--muted-foreground)", border: "1px solid var(--border)" }
                }
              >
                {label}
              </Link>
            );
          })}
        </div>

        <Suspense fallback={null}>
          <JobFilters profiles={profileOptions} roleCategories={roleCategories} />
        </Suspense>

        {jobs.length === 0 ? (
          <div className="rounded-xl border border-dashed py-16 text-center mt-4" style={{ borderColor: "var(--border)" }}>
            <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>No roles match the current filters.</p>
            <Link
              href="/workspace"
              className="inline-flex items-center gap-1.5 mt-3 text-sm font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              Start Discovery →
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5 mt-4">
            {jobs.map((job) => {
              const fr = fitMap.get(job.id);
              const score = fr?.overall_match_score;
              const ms = matchStyle(score);
              const badge = matchBadge(ms);
              const isPartial = ms === "partial";

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
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className={`py-[3px] px-2.5 rounded text-xs font-medium ${badge.classes}`}>
                      {badge.text}
                    </span>
                    <div className="flex-1" />
                    <div className="flex items-center gap-3 shrink-0">
                      <JobFitCell
                        jobId={job.id}
                        jobReportId={job.latest_job_report_id}
                        hasProfile={!!activeProfileId}
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

                  <Link href={`/jobs/${job.id}`} className="block group">
                    <div
                      className="text-base font-semibold mb-1 group-hover:underline"
                      style={{ color: isPartial ? "oklch(28% 0.012 275)" : "oklch(16% 0.015 275)" }}
                    >
                      {job.title}
                    </div>
                    <div className="text-[13px] mb-3" style={{ color: "oklch(56% 0.01 275)" }}>
                      {job.company}
                      {job.location && ` · ${job.location}`}
                      {job.seniority_inferred && ` · ${job.seniority_inferred}`}
                    </div>
                  </Link>

                  <div className="pt-3 flex items-center justify-between" style={{ borderTop: "1px solid oklch(93% 0.008 280)" }}>
                    <div className="flex items-center gap-4">
                      <span className="text-xs" style={{ color: "oklch(60% 0.01 275)" }}>
                        Discovered {fmtTs(job.created_at.toString())}
                      </span>
                      <ArchiveJobButton jobId={job.id} />
                    </div>
                    <Link
                      href={`/jobs/${job.id}`}
                      className="text-[12.5px] font-medium hover:underline"
                      style={{ color: isPartial ? "oklch(62% 0.01 275)" : "var(--primary)" }}
                    >
                      View role →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
