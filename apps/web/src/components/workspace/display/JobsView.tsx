"use client";

import { useState, useEffect } from "react";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, RefreshCw } from "lucide-react";

interface JobsViewProps {
  workspaceId: string;
  activeJobId?: string;
  onJobSelected: (id: string) => void;
}

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-zinc-100 text-zinc-600";
}

export function JobsView({ workspaceId, activeJobId, onJobSelected }: JobsViewProps) {
  const [jobs, setJobs] = useState<JobRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchJobs() {
    setLoading(true);
    setError(null);
    try {
      const list = await listJobs(workspaceId);
      setJobs(list.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  if (loading) {
    return <p className="text-xs text-zinc-400 py-8 text-center">Loading jobs…</p>;
  }

  if (error) {
    return (
      <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between pb-1">
        <p className="text-xs text-zinc-500">{jobs.length} job{jobs.length !== 1 ? "s" : ""}</p>
        <button
          onClick={fetchJobs}
          className="p-1 rounded text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      {jobs.length === 0 && (
        <p className="text-xs text-zinc-400 py-8 text-center">No jobs yet.</p>
      )}

      <ul className="space-y-1.5">
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              onClick={() => onJobSelected(job.id)}
              className={[
                "w-full flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                activeJobId === job.id
                  ? "border-zinc-800 bg-zinc-50"
                  : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
              ].join(" ")}
            >
              <div className="flex-1 min-w-0 space-y-0.5">
                <p className="text-xs font-semibold text-zinc-800 truncate">{job.title}</p>
                <div className="flex items-center gap-2 text-[11px] text-zinc-500 flex-wrap">
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
                <p className="text-[10px] text-zinc-400">{fmtTs(job.created_at)}</p>
              </div>
              <Badge className={jobStatusBg(job.status) + " text-[10px] shrink-0 self-start mt-0.5"}>
                {job.status}
              </Badge>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
