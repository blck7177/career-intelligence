"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Building2, MapPin, RefreshCw, ExternalLink } from "lucide-react";

interface JobsPanelProps {
  activeJobId?: string;
  onJobSelected: (id: string) => void;
}

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-zinc-100 text-zinc-600";
}

export function JobsPanel({ activeJobId, onJobSelected }: JobsPanelProps) {
  const { getToken } = useAuth();
  const [jobs, setJobs] = useState<JobRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchJobs() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const list = await listJobs(token);
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
  }, []);

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-800">Jobs</h2>
          <p className="text-xs text-zinc-500 mt-0.5">
            {jobs.length} job{jobs.length !== 1 ? "s" : ""} in database
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={fetchJobs}
            disabled={loading}
            className="p-1.5 rounded text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <Link
            href="/jobs"
            className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-600 px-1.5 py-1 rounded hover:bg-zinc-100 transition-colors"
            title="Open full database"
          >
            <ExternalLink size={12} />
          </Link>
        </div>
      </div>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      {!loading && jobs.length === 0 && !error && (
        <p className="text-xs text-zinc-400 py-4 text-center">
          No jobs yet. Use Discovery to find jobs.
        </p>
      )}

      <ul className="space-y-1">
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              onClick={() => onJobSelected(job.id)}
              className={[
                "w-full flex items-start gap-2 px-3 py-2.5 rounded-lg border text-left transition-colors",
                activeJobId === job.id
                  ? "border-zinc-800 bg-zinc-50"
                  : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
              ].join(" ")}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <p className="text-xs font-medium text-zinc-800 truncate">{job.title}</p>
                  <Badge className={jobStatusBg(job.status) + " text-[10px] shrink-0"}>
                    {job.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-zinc-500 mt-0.5">
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
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
