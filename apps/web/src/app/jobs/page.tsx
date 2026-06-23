import Link from "next/link";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, Plus, ExternalLink } from "lucide-react";

export const dynamic = "force-dynamic";

const WORKSPACE_ID = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_default";

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  if (status === "stale") return "bg-zinc-100 text-zinc-600";
  return "bg-zinc-100 text-zinc-600";
}

function JobRow({ job }: { job: JobRead }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="flex items-start justify-between border border-zinc-200 rounded-lg p-4 hover:bg-zinc-50 transition-colors gap-4"
    >
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold text-zinc-900 truncate">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-xs shrink-0"}>
            {job.status}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500 flex-wrap">
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
          <span className="text-zinc-400">{job.source_type}</span>
        </div>
        <p className="text-xs text-zinc-400">Discovered {fmtTs(job.created_at.toString())}</p>
      </div>
      <ExternalLink size={14} className="text-zinc-300 shrink-0 mt-0.5" />
    </Link>
  );
}

export default async function JobsPage() {
  let jobs: JobRead[] = [];
  let fetchError: string | null = null;
  let total = 0;

  try {
    const list = await listJobs(WORKSPACE_ID);
    jobs = list.items;
    total = list.total;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load jobs";
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Job Database</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {total} job{total !== 1 ? "s" : ""} discovered
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

      {jobs.length === 0 && !fetchError && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center space-y-3">
          <p className="text-zinc-500 text-sm font-medium">No jobs yet</p>
          <p className="text-zinc-400 text-xs">
            Run a Discovery search to find and ingest job listings.
          </p>
          <Link href="/workspace">
            <Button size="sm" variant="outline" className="mt-2">
              <Plus size={13} className="mr-1.5" />
              Start Discovery
            </Button>
          </Link>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="space-y-2">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </div>
      )}
    </div>
  );
}
