import { getTranslations } from "next-intl/server";
import { Briefcase } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { listJobs, listFitReports, getProfile } from "@/api/client";
import type { FitReportSummary, JobRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { JobsMasterDetail } from "./JobsMasterDetail";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";

// Backend caps `limit` at 500; filters below run client-side over this
// fetched batch, so jobs beyond this count won't be visible until we
// move filtering server-side.
const FETCH_LIMIT = 500;
const PAGE_SIZE = 20;

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
    favorites?: string;
    not_interested?: string;
    selected?: string;
    page?: string;
  }>;
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

function uniqueCompanies(jobs: JobRead[]): string[] {
  const set = new Set<string>();
  for (const j of jobs) {
    if (j.company) set.add(j.company);
  }
  return [...set].sort();
}

export default async function JobsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const token = await getServerToken();
  const t = await getTranslations("jobs");

  const statusFilter = (params.status as StatusFilter) || "all";
  const profileId = params.profile_id;
  const favoritesOnly = params.favorites === "1";
  const notInterestedOnly = params.not_interested === "1";

  const [jobList, profile] = await Promise.all([
    listJobs(
      {
        status: statusFilter !== "all" ? statusFilter : undefined,
        include_report_summary: true,
        favorites_only: favoritesOnly,
        not_interested_only: notInterestedOnly,
        limit: FETCH_LIMIT,
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

  // Build fit map (first fit report per job)
  const fitMap = new Map<string, FitReportSummary>();
  for (const fr of fitListData.items) {
    if (!fitMap.has(fr.job_id)) fitMap.set(fr.job_id, fr);
  }

  const activeProfileId = resolvedProfileId;

  // Sorting — mirrors JobFilters' effectiveSort so the dropdown never shows
  // one order while the list renders another.
  const effectiveSort = params.sort || (activeProfileId ? "fit" : "newest");
  if (effectiveSort === "fit" && activeProfileId) {
    jobs = [...jobs].sort((a, b) => {
      const sa = fitMap.get(a.id)?.overall_match_score ?? -1;
      const sb = fitMap.get(b.id)?.overall_match_score ?? -1;
      return sb - sa;
    });
  } else if (effectiveSort === "oldest") {
    jobs = [...jobs].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  } else if (effectiveSort === "company") {
    jobs = [...jobs].sort((a, b) => a.company.localeCompare(b.company));
  }

  const roleCategories = uniqueRoleCategories(jobList.items);
  const companies = uniqueCompanies(jobList.items);
  const profileOptions = profile
    ? [{ id: profile.id, label: profile.summary?.slice(0, 40) ?? t("yourProfile") }]
    : [];

  // Serialize fit map to a plain object for the client component.
  const fitMapObj: Record<string, { id: string; score: number; recommended_next_action?: string | null }> = {};
  for (const [jobId, fr] of fitMap) {
    fitMapObj[jobId] = {
      id: fr.id,
      score: fr.overall_match_score,
      recommended_next_action: fr.recommended_next_action,
    };
  }

  const totalCount = jobs.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, Number(params.page) || 1), totalPages);
  const pagedJobs = jobs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  // Truly-empty library (no jobs at all, unfiltered) → full-width call to
  // action. A non-empty library that filters down to zero falls through to
  // the master-detail, which shows its own in-column empty state.
  if (jobList.items.length === 0) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <EmptyState
          icon={Briefcase}
          title={t("emptyTitle")}
          action={
            <Link
              href="/workspace"
              className="inline-flex items-center gap-1.5 text-sm font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              {t("startDiscovery")}
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <JobsMasterDetail
      jobs={pagedJobs.map((j) => ({
        id: j.id,
        title: j.title,
        company: j.company,
        location: j.location,
        status: j.status,
        seniority_inferred: j.seniority_inferred,
        created_at: j.created_at.toString(),
        latest_job_report_id: j.latest_job_report_id,
        is_favorited: j.is_favorited,
        is_not_interested: j.is_not_interested,
        is_applied: j.is_applied,
      }))}
      fitMap={fitMapObj}
      profile={profile}
      profileId={activeProfileId ?? null}
      profiles={profileOptions}
      roleCategories={roleCategories}
      companies={companies}
      favoritesOnly={favoritesOnly}
      notInterestedOnly={notInterestedOnly}
      statusFilter={statusFilter}
      totalCount={totalCount}
      currentPage={currentPage}
      totalPages={totalPages}
    />
  );
}
