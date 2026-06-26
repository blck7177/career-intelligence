import Link from "next/link";
import { Suspense } from "react";
import { listJobs, listFitReports, getProfile } from "@/api/client";
import type { FitReportSummary, JobRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Building2, MapPin, Plus, Search, ChevronRight } from "lucide-react";
import { fmtTs } from "@/lib/utils";
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

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  if (status === "stale") return "bg-zinc-100 text-zinc-500";
  return "bg-zinc-100 text-zinc-600";
}

function jobStatusLabel(status: string): string {
  const MAP: Record<string, string> = {
    reportable: "Report Ready",
    discovered: "Needs Report",
    stale: "Stale",
    invalid: "Invalid",
  };
  return MAP[status] ?? status;
}

function statusDot(status: string): string {
  if (status === "reportable") return "bg-emerald-400";
  if (status === "discovered") return "bg-blue-400";
  if (status === "stale") return "bg-zinc-300";
  if (status === "invalid") return "bg-rose-400";
  return "bg-zinc-300";
}

function ConfidenceBadge({ c }: { c: string }) {
  if (c === "high") return <Badge className="bg-emerald-100 text-emerald-800 border-0 text-[10px]">High</Badge>;
  if (c === "medium") return <Badge className="bg-amber-100 text-amber-800 border-0 text-[10px]">Medium</Badge>;
  return <Badge className="bg-rose-100 text-rose-800 border-0 text-[10px]">Low</Badge>;
}

function shortRoleCategory(ws: string) {
  return ws.split(" / ")[0];
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
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Role Inbox</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {jobs.length} role{jobs.length !== 1 ? "s" : ""}
            {activeProfileId && fitMap.size > 0 && ` · sorted by fit score`}
            {activeFilters > 0 &&
              ` · ${activeFilters} filter${activeFilters !== 1 ? "s" : ""} active`}
          </p>
        </div>
        <Link href="/workspace">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            New Discovery
          </Button>
        </Link>
      </div>

      {/* Saved views */}
      <div className="flex flex-wrap gap-2">
        {SAVED_VIEWS.map(({ label, status }) => {
          const active = statusFilter === status;
          return (
            <Link
              key={status}
              href={`/jobs${buildQuery(params, { status: status === "all" ? undefined : status })}`}
              className={[
                "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
                active
                  ? "bg-indigo-600 text-white border-indigo-600"
                  : "bg-white text-zinc-600 border-zinc-200 hover:border-zinc-300",
              ].join(" ")}
            >
              {label}
            </Link>
          );
        })}
      </div>

      <Suspense fallback={null}>
        <JobFilters profiles={profileOptions} roleCategories={roleCategories} />
      </Suspense>

      {!params.profile_id && profile && (
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-xs text-indigo-800">
          Showing fit scores for your profile. Use the filter above to change context.
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-200 py-16 text-center space-y-3">
          <p className="text-sm text-zinc-500">No roles match the current filters.</p>
          <Link href="/workspace">
            <Button size="sm" variant="outline">
              <Search size={13} className="mr-1.5" />
              Start Discovery
            </Button>
          </Link>
        </div>
      ) : (
        <div className="space-y-2.5">
          {jobs.map((job) => {
            const fr = fitMap.get(job.id);
            return (
              <div
                key={job.id}
                className="flex items-start gap-3 border border-zinc-200 rounded-lg bg-white hover:border-zinc-300 hover:shadow-sm transition-all group"
              >
                <Link
                  href={`/jobs/${job.id}`}
                  className="flex flex-1 items-start gap-3 min-w-0 p-4 pr-0"
                >
                  <div className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${statusDot(job.status)}`} />

                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap min-w-0">
                        <p className="text-sm font-semibold text-zinc-900 leading-snug truncate">
                          {job.title}
                        </p>
                        {job.role_category_confidence && (
                          <ConfidenceBadge c={job.role_category_confidence} />
                        )}
                      </div>
                      <Badge className={jobStatusBg(job.status) + " text-[10px] shrink-0"}>
                        {jobStatusLabel(job.status)}
                      </Badge>
                    </div>

                    <div className="flex items-center gap-2.5 text-xs text-zinc-500 flex-wrap">
                      <span className="flex items-center gap-1">
                        <Building2 size={11} />
                        {job.company}
                      </span>
                      {job.location && (
                        <span className="flex items-center gap-1">
                          <MapPin size={11} />
                          {job.location}
                        </span>
                      )}
                    </div>

                    {(job.primary_role_category || job.seniority_inferred) && (
                      <div className="flex flex-wrap gap-1.5 pt-0.5">
                        {job.primary_role_category && job.primary_role_category !== "unknown" && (
                          <Badge variant="secondary" className="text-[10px]">
                            {shortRoleCategory(job.primary_role_category)}
                          </Badge>
                        )}
                        {job.seniority_inferred && (
                          <Badge variant="outline" className="text-[10px] text-zinc-500">
                            {job.seniority_inferred}
                          </Badge>
                        )}
                      </div>
                    )}

                    <p className="text-xs text-zinc-400">
                      Discovered {fmtTs(job.created_at.toString())}
                    </p>
                  </div>
                </Link>

                <div className="flex flex-col items-end gap-2 shrink-0 p-4 pl-2">
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
                  <Link href={`/jobs/${job.id}`} className="text-zinc-300 group-hover:text-zinc-400">
                    <ChevronRight size={14} />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
