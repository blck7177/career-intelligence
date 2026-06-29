import Link from "next/link";
import { Suspense } from "react";
import { listJobs, listFitReports, getProfile } from "@/api/client";
import type { FitReportSummary, JobRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { JobFilters } from "./JobFilters";
import { JobListClient } from "./JobListClient";

export const dynamic = "force-dynamic";

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";

interface PageProps {
  searchParams: Promise<{
    profile_id?: string;
    role_category?: string;
    seniority?: string;
    confidence?: string;
    company?: string;
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

function uniqueRoleCategories(jobs: JobRead[]): string[] {
  const set = new Set<string>();
  for (const j of jobs) {
    if (j.primary_role_category && j.primary_role_category !== "unknown") {
      set.add(j.primary_role_category);
    }
  }
  return [...set].sort();
}

function uniqueCompanies(jobs: JobRead[]): string[] {
  const set = new Set<string>();
  for (const j of jobs) {
    if (j.company) set.add(j.company);
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

  // Client-side filters
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
  if (params.company) {
    jobs = jobs.filter((j) => j.company === params.company);
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

  // Build fit map
  const fitMap = new Map<string, FitReportSummary>();
  for (const fr of fitListData.items) {
    if (!fitMap.has(fr.job_id)) {
      fitMap.set(fr.job_id, fr);
    }
  }

  const activeProfileId = resolvedProfileId;

  // Sorting
  const sortParam = params.sort;
  if (sortParam === "fit" && activeProfileId) {
    jobs = [...jobs].sort((a, b) => {
      const sa = fitMap.get(a.id)?.overall_match_score ?? -1;
      const sb = fitMap.get(b.id)?.overall_match_score ?? -1;
      return sb - sa;
    });
  } else if (sortParam === "oldest") {
    jobs = [...jobs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  } else if (sortParam === "company") {
    jobs = [...jobs].sort((a, b) => a.company.localeCompare(b.company));
  } else if (!sortParam && activeProfileId) {
    // Default: sort by fit when profile is selected
    jobs = [...jobs].sort((a, b) => {
      const sa = fitMap.get(a.id)?.overall_match_score ?? -1;
      const sb = fitMap.get(b.id)?.overall_match_score ?? -1;
      return sb - sa;
    });
  }
  // Default (no sort param, no profile): API returns newest first

  const roleCategories = uniqueRoleCategories(jobList.items);
  const companies = uniqueCompanies(jobList.items);
  const profileOptions = profile
    ? [{ id: profile.id, label: profile.summary?.slice(0, 40) ?? "Your Profile" }]
    : [];

  const activeFilters = [
    params.profile_id,
    params.role_category,
    params.seniority,
    params.confidence,
    params.company,
    params.q,
  ].filter(Boolean).length;

  // Serialize fitMap to plain object for client component
  const fitMapObj: Record<string, { id: string; score: number; recommended_next_action?: string | null }> = {};
  for (const [jobId, fr] of fitMap) {
    fitMapObj[jobId] = {
      id: fr.id,
      score: fr.overall_match_score,
      recommended_next_action: fr.recommended_next_action,
    };
  }

  return (
    <>
      {/* Header */}
      <header
        className="h-[56px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-base font-semibold" style={{ color: "var(--foreground)" }}>
          Saved Roles
        </span>
        <span className="text-[13px]" style={{ color: "var(--muted-foreground)" }}>
          {jobs.length} role{jobs.length !== 1 ? "s" : ""}
          {activeFilters > 0 && ` · ${activeFilters} filter${activeFilters !== 1 ? "s" : ""}`}
        </span>
        <div className="flex-1" />
        <Link
          href="/workspace"
          className="flex items-center gap-2 h-9 px-4 rounded-lg text-[13px] font-semibold text-white shrink-0 transition-all hover:opacity-90 shadow-sm hover:shadow"
          style={{ background: "var(--primary)" }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12">
            <line x1="6" y1="1" x2="6" y2="11" stroke="white" strokeWidth="2" strokeLinecap="round" />
            <line x1="1" y1="6" x2="11" y2="6" stroke="white" strokeWidth="2" strokeLinecap="round" />
          </svg>
          New Search
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto px-7 py-6">
        {/* Status filter pills */}
        <div className="flex flex-wrap gap-2 mb-5">
          {SAVED_VIEWS.map(({ label, status }) => {
            const active = statusFilter === status;
            return (
              <Link
                key={status}
                href={`/jobs${buildQuery(params, { status: status === "all" ? undefined : status })}`}
                className="py-[6px] px-4 rounded-full text-[13px] font-medium transition-colors"
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
          <JobFilters profiles={profileOptions} roleCategories={roleCategories} companies={companies} />
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
          <div className="mt-4">
            <JobListClient
              jobs={jobs.map((j) => ({
                id: j.id,
                title: j.title,
                company: j.company,
                location: j.location,
                status: j.status,
                seniority_inferred: j.seniority_inferred,
                created_at: j.created_at.toString(),
                latest_job_report_id: j.latest_job_report_id,
              }))}
              fitMap={fitMapObj}
              hasProfile={!!activeProfileId}
              profileId={activeProfileId}
            />
          </div>
        )}
      </div>
    </>
  );
}
