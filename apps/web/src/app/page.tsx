import Link from "next/link";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, Plus, ExternalLink, Database, BarChart3, FileSearch, Archive } from "lucide-react";

export const dynamic = "force-dynamic";

const WORKSPACE_ID = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_default";

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-zinc-100 text-zinc-600";
}

function StatCard({
  label,
  value,
  icon,
  href,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 rounded-lg border border-zinc-200 bg-white p-4 hover:bg-zinc-50 transition-colors"
    >
      <div className="w-9 h-9 rounded-lg bg-zinc-100 flex items-center justify-center shrink-0 text-zinc-500">
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-zinc-900">{value}</p>
        <p className="text-xs text-zinc-500">{label}</p>
      </div>
    </Link>
  );
}

function RecentJobRow({ job }: { job: JobRead }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="flex items-center justify-between gap-3 py-2.5 border-b border-zinc-100 last:border-0 hover:bg-zinc-50 -mx-2 px-2 rounded transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-zinc-800 truncate">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-[10px] shrink-0"}>{job.status}</Badge>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500 mt-0.5">
          <span className="flex items-center gap-0.5">
            <Building2 size={10} />
            {job.company}
          </span>
          {job.location && (
            <span className="flex items-center gap-0.5">
              <MapPin size={10} />
              {job.location}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-xs text-zinc-400">{fmtTs(job.created_at.toString())}</span>
        <ExternalLink size={12} className="text-zinc-300" />
      </div>
    </Link>
  );
}

export default async function HomePage() {
  let jobs: JobRead[] = [];
  let fetchError: string | null = null;

  try {
    const list = await listJobs(WORKSPACE_ID);
    jobs = list.items;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load jobs";
  }

  const total = jobs.length;
  const reportable = jobs.filter((j) => j.status === "reportable").length;
  const discovered = jobs.filter((j) => j.status === "discovered").length;
  const staleOrInvalid = jobs.filter((j) => j.status === "stale" || j.status === "invalid").length;

  const recentJobs = [...jobs]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Job Database</h1>
          <p className="text-zinc-500 text-sm mt-1">
            Your career intelligence workspace
          </p>
        </div>
        <Link href="/workspace">
          <Button size="sm">
            <Plus size={14} className="mr-1.5" />
            Add Jobs
          </Button>
        </Link>
      </div>

      {fetchError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {fetchError}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total jobs"
          value={total}
          icon={<Database size={16} />}
          href="/jobs"
        />
        <StatCard
          label="Has report"
          value={reportable}
          icon={<BarChart3 size={16} />}
          href="/jobs"
        />
        <StatCard
          label="Needs report"
          value={discovered}
          icon={<FileSearch size={16} />}
          href="/jobs"
        />
        <StatCard
          label="Stale / invalid"
          value={staleOrInvalid}
          icon={<Archive size={16} />}
          href="/jobs"
        />
      </div>

      {/* Saved view shortcuts */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-700">Quick Views</h2>
        <div className="flex gap-2 flex-wrap">
          {[
            { label: "All Jobs", href: "/jobs" },
            { label: "Has Report", href: "/jobs" },
            { label: "Needs Report", href: "/jobs" },
            { label: "Stale", href: "/jobs" },
          ].map((view) => (
            <Link
              key={view.label}
              href={view.href}
              className="px-3 py-1.5 rounded-full border border-zinc-300 text-xs text-zinc-600 hover:border-zinc-400 hover:text-zinc-900 hover:bg-zinc-50 transition-colors"
            >
              {view.label}
            </Link>
          ))}
        </div>
      </div>

      {/* Recent jobs */}
      {recentJobs.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-700">Recent Jobs</h2>
            <Link href="/jobs" className="text-xs text-zinc-400 hover:text-zinc-700">
              View all →
            </Link>
          </div>
          <div className="rounded-lg border border-zinc-200 bg-white px-4 py-2">
            {recentJobs.map((job) => (
              <RecentJobRow key={job.id} job={job} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {total === 0 && !fetchError && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center space-y-3">
          <p className="text-zinc-500 text-sm font-medium">No jobs in database yet</p>
          <p className="text-zinc-400 text-xs">
            Start a Discovery run to find and import job listings.
          </p>
          <Link href="/workspace">
            <Button size="sm" variant="outline" className="mt-2">
              <Plus size={13} className="mr-1.5" />
              Start Discovery
            </Button>
          </Link>
        </div>
      )}
    </div>
  );
}
