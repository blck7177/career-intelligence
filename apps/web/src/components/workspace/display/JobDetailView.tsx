"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useApiToken } from "@/hooks/useApiToken";
import { getJob, getLatestJobReport, createRun } from "@/api/client";
import type { JobRead, JobReportResponse } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import {
  Building2,
  MapPin,
  Globe,
  ExternalLink,
  FileText,
  Loader2,
  Play,
} from "lucide-react";

interface JobDetailViewProps {
  jobId: string;
  onRunCreated: (runId: string) => void;
}

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-zinc-100 text-zinc-600";
}

function MetaRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-xs">
      <dt className="w-28 shrink-0 text-zinc-400">{label}</dt>
      <dd className="text-zinc-700 font-mono break-all">{value}</dd>
    </div>
  );
}

function JobReportContent({ report }: { report: JobReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  return (
    <div className="space-y-2.5 text-xs text-zinc-700">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-zinc-500">Job Intelligence Report</span>
        <Badge className="bg-emerald-100 text-emerald-700 text-[10px]">{report.status}</Badge>
        {report.used_research && (
          <Badge className="bg-blue-100 text-blue-700 text-[10px]">with research</Badge>
        )}
      </div>
      {(s.primary_workstream as string | undefined) && (
        <div>
          <p className="font-medium text-zinc-500 mb-0.5">Role category</p>
          <p>{s.primary_workstream as string}</p>
        </div>
      )}
      {(s.business_context as string | undefined) && (
        <div>
          <p className="font-medium text-zinc-500 mb-0.5">Business Context</p>
          <p className="leading-relaxed">{s.business_context as string}</p>
        </div>
      )}
      {(s.position_function as string | undefined) && (
        <div>
          <p className="font-medium text-zinc-500 mb-0.5">Position Function</p>
          <p className="leading-relaxed">{s.position_function as string}</p>
        </div>
      )}
      {(s.uncertainty_notes as string | undefined) && (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="font-medium text-amber-700 mb-0.5">Uncertainty Notes</p>
          <p className="text-amber-700">{s.uncertainty_notes as string}</p>
        </div>
      )}
      <p className="text-zinc-400 pt-1 font-mono text-[10px]">
        {report.id} · v{report.prompt_version}
      </p>
    </div>
  );
}

export function JobDetailView({ jobId, onRunCreated }: JobDetailViewProps) {
  const getToken = useApiToken();
  const [job, setJob] = useState<JobRead | null>(null);
  const [report, setReport] = useState<JobReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setReport(null);

    getToken().then((token) =>
      Promise.all([
        getJob(jobId, token),
        getLatestJobReport(jobId, token).catch(() => null),
      ])
    )
      .then(([j, r]) => {
        setJob(j);
        setReport(r);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load job"))
      .finally(() => setLoading(false));
  }, [jobId, getToken]);

  async function handleGenerateReport() {
    if (!job) return;
    setReportLoading(true);
    setReportError(null);
    try {
      const token = await getToken();
      const run = await createRun({
        run_type: "job_report",
        input_snapshot: {
          job_id: jobId,
          use_research: false,
          force_refresh: false,
        },
      }, token);
      onRunCreated(run.id);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Failed to start job report run");
    } finally {
      setReportLoading(false);
    }
  }

  if (loading) {
    return <p className="text-xs text-zinc-400 py-8 text-center">Loading job…</p>;
  }

  if (error || !job) {
    return (
      <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
        {error ?? "Job not found"}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-start gap-2 flex-wrap">
          <p className="text-sm font-semibold text-zinc-900 flex-1">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-xs shrink-0"}>{job.status}</Badge>
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
        </div>
        <a
          href={job.canonical_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <Globe size={10} />
          View posting
          <ExternalLink size={9} />
        </a>
      </div>

      {/* Database metadata */}
      <div className="rounded-lg border border-zinc-100 bg-zinc-50/60 p-3 space-y-1">
        <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">
          Database Metadata
        </p>
        <dl className="space-y-1">
          <MetaRow label="Source" value={job.source_type} />
          <MetaRow label="Discovered" value={fmtTs(job.created_at)} />
          <MetaRow label="Last seen" value={job.last_seen_at ? fmtTs(job.last_seen_at) : null} />
          <MetaRow label="Discovery run" value={job.discovered_run_id} />
          <div className="flex gap-2 text-xs">
            <dt className="w-28 shrink-0 text-zinc-400">Report</dt>
            <dd className={report ? "text-emerald-600 font-medium" : "text-zinc-400"}>
              {report ? "Available" : "Not generated"}
            </dd>
          </div>
        </dl>
      </div>

      {/* Actions */}
      <div className="space-y-2">
        <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">Actions</p>

        <Button
          onClick={handleGenerateReport}
          disabled={reportLoading}
          size="sm"
          variant={report ? "outline" : "default"}
          className="w-full justify-start"
        >
          {reportLoading ? (
            <Loader2 size={13} className="animate-spin mr-2" />
          ) : (
            <FileText size={13} className="mr-2" />
          )}
          {report ? "Refresh Job Report" : "Generate Job Report"}
        </Button>
        {reportError && (
          <p className="text-xs text-rose-600">{reportError}</p>
        )}

        <div className="flex gap-2 flex-wrap">
          {(["Find Similar", "Interview Prep", "Outreach"] as const).map((label) => (
            <span
              key={label}
              className="inline-flex items-center gap-1 rounded border border-zinc-200 px-2 py-1 text-[10px] text-zinc-400"
            >
              {label}
              <span className="text-zinc-300">· soon</span>
            </span>
          ))}
        </div>
      </div>

      {/* Report content */}
      <div className="border-t border-zinc-100 pt-4">
        {report ? (
          <JobReportContent report={report} />
        ) : (
          <div className="flex flex-col items-center justify-center py-8 gap-2 rounded-lg border border-dashed border-zinc-200 text-center">
            <FileText size={20} className="text-zinc-300" />
            <p className="text-xs font-medium text-zinc-500">No Job Intelligence Report yet</p>
            <p className="text-xs text-zinc-400">Generate a report to see analysis.</p>
            <Button
              onClick={handleGenerateReport}
              disabled={reportLoading}
              size="sm"
              variant="outline"
              className="mt-1"
            >
              {reportLoading ? (
                <Loader2 size={12} className="animate-spin mr-1.5" />
              ) : (
                <Play size={12} className="mr-1.5" />
              )}
              Generate Now
            </Button>
          </div>
        )}
      </div>

      {/* Full detail link */}
      <div className="pt-1 border-t border-zinc-100">
        <Link
          href={`/jobs/${job.id}`}
          className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-900 transition-colors"
        >
          Open full detail
          <ExternalLink size={11} />
        </Link>
      </div>
    </div>
  );
}
