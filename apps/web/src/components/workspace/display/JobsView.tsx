"use client";

import { useState, useEffect } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { listJobs } from "@/api/client";
import type { JobRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { fmtTs } from "@/lib/utils";
import { Building2, MapPin, RefreshCw, Briefcase, AlertTriangle } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";

interface JobsViewProps {
  activeJobId?: string;
  onJobSelected: (id: string) => void;
}

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-[var(--muted)] text-[var(--ink-secondary)]";
}

export function JobsView({ activeJobId, onJobSelected }: JobsViewProps) {
  const getToken = useApiToken();
  const [jobs, setJobs] = useState<JobRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchJobs() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const list = await listJobs(undefined, token);
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

  if (loading) {
    return <EmptyState icon={Briefcase} title="Loading jobs…" compact />;
  }

  if (error) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
        <AlertTriangle size={12} className="shrink-0" />
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between pb-1">
        <p className="text-xs text-[var(--ink-muted)]">{jobs.length} job{jobs.length !== 1 ? "s" : ""}</p>
        <button
          onClick={fetchJobs}
          className="p-1 rounded text-[var(--ink-muted)] hover:text-[var(--ink-secondary)] hover:bg-[var(--muted)] transition-colors"
          title="Refresh"
        >
          <RefreshCw size={12} />
        </button>
      </div>

      {jobs.length === 0 && <EmptyState icon={Briefcase} title="No jobs yet." compact />}

      <ul className="space-y-1.5">
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              onClick={() => onJobSelected(job.id)}
              className={[
                "w-full flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                activeJobId === job.id
                  ? "border-[var(--primary)] bg-[var(--muted)]"
                  : "border-[var(--border)] hover:border-[var(--ink-faint)] hover:bg-[var(--muted)]",
              ].join(" ")}
            >
              <div className="flex-1 min-w-0 space-y-0.5">
                <p className="text-xs font-semibold text-[var(--ink-primary)] truncate">{job.title}</p>
                <div className="flex items-center gap-2 text-[11px] text-[var(--ink-muted)] flex-wrap">
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
                <p className="text-[10px] text-[var(--ink-muted)]">{fmtTs(job.created_at)}</p>
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
