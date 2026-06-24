import Link from "next/link";
import { listJobs, listRuns } from "@/api/client";
import type { JobRead, RunRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Building2,
  MapPin,
  Plus,
  Inbox,
  BarChart3,
  Search,
  CheckCircle2,
  XCircle,
  Circle,
  AlertCircle,
  Clock,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { fmtTs } from "@/lib/utils";

export const dynamic = "force-dynamic";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RUN_TYPE_LABELS: Record<string, string> = {
  job_discovery: "Discovery Run",
  job_report: "Job Intelligence Report",
  fit_report: "Fit Analysis",
};

function runTypeLabel(t: string) {
  return RUN_TYPE_LABELS[t] ?? t.replace(/_/g, " ");
}

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "In Progress",
  succeeded: "Completed",
  failed: "Failed",
  needs_review: "Needs Review",
  cancelled: "Cancelled",
};

function humanRunStatus(s: string) {
  return RUN_STATUS_LABELS[s] ?? s.replace(/_/g, " ");
}

function runStatusBadge(status: string): string {
  if (status === "succeeded") return "bg-emerald-100 text-emerald-700";
  if (status === "running") return "bg-blue-100 text-blue-700";
  if (status === "queued") return "bg-zinc-100 text-zinc-600";
  if (status === "needs_review") return "bg-amber-100 text-amber-700";
  if (status === "failed") return "bg-rose-100 text-rose-700";
  return "bg-zinc-100 text-zinc-500";
}

function jobStatusDot(status: string): string {
  if (status === "reportable") return "bg-emerald-400";
  if (status === "discovered") return "bg-blue-400";
  return "bg-zinc-300";
}

function RunStatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={13} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={13} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={13} className="text-blue-500 animate-pulse shrink-0" />;
  return <Clock size={13} className="text-zinc-400 shrink-0" />;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SummaryCard({
  label,
  value,
  sub,
  icon,
  href,
  accent,
}: {
  label: string;
  value: number | string;
  sub?: string;
  icon: React.ReactNode;
  href: string;
  accent?: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 hover:border-zinc-300 hover:shadow-sm transition-all group"
    >
      <div
        className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${accent ?? "bg-zinc-100 text-zinc-500"}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xl font-bold text-zinc-900 leading-tight">{value}</p>
        <p className="text-xs font-medium text-zinc-600 mt-0.5">{label}</p>
        {sub && <p className="text-[10px] text-zinc-400 mt-0.5">{sub}</p>}
      </div>
      <ChevronRight size={14} className="text-zinc-200 group-hover:text-zinc-400 transition-colors ml-auto mt-0.5 shrink-0" />
    </Link>
  );
}

function RecentRunRow({ run }: { run: RunRead }) {
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex items-center justify-between gap-3 py-2.5 border-b border-zinc-100 last:border-0 hover:bg-zinc-50 -mx-3 px-3 rounded transition-colors"
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <RunStatusIcon status={run.status} />
        <div className="min-w-0">
          <p className="text-xs font-medium text-zinc-700 truncate">{runTypeLabel(run.run_type)}</p>
          <p className="text-[10px] text-zinc-400">{fmtTs(run.created_at)}</p>
        </div>
      </div>
      <Badge className={runStatusBadge(run.status) + " text-[10px] shrink-0"}>
        {humanRunStatus(run.status)}
      </Badge>
    </Link>
  );
}

function RecentRoleRow({ job }: { job: JobRead }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="flex items-center justify-between gap-3 py-2.5 border-b border-zinc-100 last:border-0 hover:bg-zinc-50 -mx-3 px-3 rounded transition-colors"
    >
      <div className="flex items-center gap-2 min-w-0">
        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${jobStatusDot(job.status)}`} />
        <div className="min-w-0">
          <p className="text-xs font-medium text-zinc-700 truncate">{job.title}</p>
          <div className="flex items-center gap-1.5 text-[10px] text-zinc-400">
            <span className="flex items-center gap-0.5">
              <Building2 size={9} />
              {job.company}
            </span>
            {job.location && (
              <span className="flex items-center gap-0.5">
                <MapPin size={9} />
                {job.location}
              </span>
            )}
          </div>
        </div>
      </div>
      <span className="text-[10px] text-zinc-400 shrink-0">{fmtTs(job.created_at.toString())}</span>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function HomePage() {
  const token = await getServerToken();

  let jobs: JobRead[] = [];
  let runs: RunRead[] = [];
  let fetchError: string | null = null;

  try {
    const [jobList, runList] = await Promise.all([
      listJobs(token),
      listRuns(token).catch(() => ({ items: [] as RunRead[] })),
    ]);
    jobs = jobList.items;
    runs = runList.items;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load data";
  }

  const total = jobs.length;
  const reportable = jobs.filter((j) => j.status === "reportable").length;
  const discovered = jobs.filter((j) => j.status === "discovered").length;

  const oneWeekAgo = new Date();
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
  const newThisWeek = jobs.filter((j) => new Date(j.created_at) > oneWeekAgo).length;

  const discoveryRuns = runs
    .filter((r) => r.run_type === "job_discovery")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  const recentRoles = [...jobs]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Command Center</h1>
          <p className="text-zinc-500 text-sm mt-1">Career intelligence overview</p>
        </div>
        <Link href="/workspace">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            New Discovery
          </Button>
        </Link>
      </div>

      {fetchError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {fetchError}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <SummaryCard
          label="Role Inbox"
          value={total}
          sub={`${discovered} need report`}
          icon={<Inbox size={16} />}
          href="/jobs"
          accent="bg-indigo-50 text-indigo-600"
        />
        <SummaryCard
          label="Reports Ready"
          value={reportable}
          sub={reportable > 0 ? "Ready to review" : "Generate reports to analyze roles"}
          icon={<BarChart3 size={16} />}
          href="/jobs"
          accent="bg-emerald-50 text-emerald-600"
        />
        <SummaryCard
          label="Recent Searches"
          value={discoveryRuns.length}
          sub={`${runs.filter((r) => r.status === "running").length} in progress`}
          icon={<Search size={16} />}
          href="/runs"
          accent="bg-amber-50 text-amber-600"
        />
      </div>

      {/* New this week banner */}
      {newThisWeek > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
          <Sparkles size={15} className="text-indigo-500 shrink-0" />
          <p className="text-sm text-indigo-700">
            <span className="font-semibold">{newThisWeek} new role{newThisWeek !== 1 ? "s" : ""}</span> added
            {" "}in the last 7 days.{" "}
            <Link href="/jobs" className="underline hover:text-indigo-900">
              View in Role Inbox →
            </Link>
          </p>
        </div>
      )}

      {/* Two-column lower sections */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent Searches */}
        <div className="rounded-xl border border-zinc-200 bg-white p-4 space-y-1">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-zinc-700">Recent Searches</h2>
            <Link href="/runs" className="text-xs text-zinc-400 hover:text-zinc-700">
              View all →
            </Link>
          </div>
          {discoveryRuns.length > 0 ? (
            discoveryRuns.map((run) => <RecentRunRow key={run.id} run={run} />)
          ) : (
            <div className="py-6 text-center space-y-2">
              <p className="text-xs text-zinc-400">No discovery runs yet</p>
              <Link href="/workspace">
                <Button size="sm" variant="outline" className="text-xs">
                  <Plus size={12} className="mr-1" />
                  Start Discovery
                </Button>
              </Link>
            </div>
          )}
        </div>

        {/* Recent Roles */}
        <div className="rounded-xl border border-zinc-200 bg-white p-4 space-y-1">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-zinc-700">Recent Roles</h2>
            <Link href="/jobs" className="text-xs text-zinc-400 hover:text-zinc-700">
              View all →
            </Link>
          </div>
          {recentRoles.length > 0 ? (
            recentRoles.map((job) => <RecentRoleRow key={job.id} job={job} />)
          ) : (
            <div className="py-6 text-center space-y-2">
              <p className="text-xs text-zinc-400">No roles in inbox yet</p>
              <Link href="/workspace">
                <Button size="sm" variant="outline" className="text-xs">
                  <Plus size={12} className="mr-1" />
                  Start Discovery
                </Button>
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
