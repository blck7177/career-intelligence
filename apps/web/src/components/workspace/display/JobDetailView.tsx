"use client";

import { useState, useEffect } from "react";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { getJob, getLatestJobReport, createRun } from "@/api/client";
import type { JobRead, JobReportResponse } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtTs } from "@/lib/utils";
import {
  Building2,
  MapPin,
  Globe,
  ExternalLink,
  FileText,
  Play,
  Compass,
  Workflow,
  ListChecks,
  StickyNote,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { JobReportContent, type JobReportLabels } from "@/components/JobReportContent";

interface JobDetailViewProps {
  jobId: string;
  onRunCreated: (runId: string) => void;
}

const JOB_REPORT_ICONS = {
  businessContext: Building2,
  positionFunction: Compass,
  dailyWorkflow: Workflow,
  skillDemands: ListChecks,
  analystNotes: StickyNote,
};

const JOB_REPORT_LABELS: JobReportLabels = {
  businessContext: "Business Context",
  positionFunction: "Position Function",
  dailyWorkflow: "Daily Workflow",
  likelyInputs: "Inputs",
  typicalAnalyses: "Typical Analyses",
  outputs: "Outputs",
  keySkillDemands: "Key Skill Demands",
  core: "Core",
  supporting: "Supporting",
  other: "Other",
  analystNotes: "Analyst Notes",
  uncertaintyNotes: "Uncertainty Notes",
  confidence: "Confidence",
  problemSolved: (text) => `Problem solved: ${text}`,
};

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-[var(--muted)] text-[var(--ink-secondary)]";
}

function MetaRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-xs">
      <dt className="w-28 shrink-0 text-[var(--ink-muted)]">{label}</dt>
      <dd className="text-[var(--ink-secondary)] font-mono break-all">{value}</dd>
    </div>
  );
}

function JobReportCard({ report }: { report: JobReportResponse }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-[var(--ink-muted)]">Job Intelligence Report</span>
        <Badge variant="match-strong" className="text-[10px]">{report.status}</Badge>
        {report.used_research && (
          <Badge variant="match-good" className="text-[10px]">with research</Badge>
        )}
      </div>
      <JobReportContent report={report} labels={JOB_REPORT_LABELS} icons={JOB_REPORT_ICONS} />
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
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-start gap-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-14 rounded-full" />
          </div>
          <Skeleton className="h-3 w-1/3" />
        </div>
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-8 w-full rounded-lg" />
      </div>
    );
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
          <p className="text-sm font-semibold text-[var(--ink-primary)] flex-1">{job.title}</p>
          <Badge className={jobStatusBg(job.status) + " text-xs shrink-0"}>{job.status}</Badge>
        </div>
        <div className="flex items-center gap-3 text-xs text-[var(--ink-muted)] flex-wrap">
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
      <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/60 p-3 space-y-1">
        <p className="text-[10px] font-semibold text-[var(--ink-muted)] uppercase tracking-wider mb-1.5">
          Database Metadata
        </p>
        <dl className="space-y-1">
          <MetaRow label="Source" value={job.source_type} />
          <MetaRow label="Discovered" value={fmtTs(job.created_at)} />
          <MetaRow label="Last seen" value={job.last_seen_at ? fmtTs(job.last_seen_at) : null} />
          <MetaRow label="Discovery run" value={job.discovered_run_id} />
          <div className="flex gap-2 text-xs">
            <dt className="w-28 shrink-0 text-[var(--ink-muted)]">Report</dt>
            <dd className={report ? "text-emerald-600 font-medium" : "text-[var(--ink-muted)]"}>
              {report ? "Available" : "Not generated"}
            </dd>
          </div>
        </dl>
      </div>

      {/* Actions */}
      <div className="space-y-2">
        <p className="text-[10px] font-semibold text-[var(--ink-muted)] uppercase tracking-wider">Actions</p>

        <Button
          onClick={handleGenerateReport}
          loading={reportLoading}
          size="sm"
          variant={report ? "outline" : "default"}
          className="w-full justify-start"
        >
          {!reportLoading && <FileText size={13} className="mr-2" />}
          {report ? "Refresh Job Report" : "Generate Job Report"}
        </Button>
        {reportError && (
          <p className="text-xs text-rose-600">{reportError}</p>
        )}

        <div className="flex gap-2 flex-wrap">
          {(["Find Similar", "Interview Prep", "Outreach"] as const).map((label) => (
            <span
              key={label}
              className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--ink-muted)]"
            >
              {label}
              <span className="text-[var(--ink-faint)]">· soon</span>
            </span>
          ))}
        </div>
      </div>

      {/* Report content */}
      <div className="border-t border-[var(--border)] pt-4">
        {report ? (
          <JobReportCard report={report} />
        ) : (
          <EmptyState
            icon={FileText}
            title="No Job Intelligence Report yet"
            hint="Generate a report to see analysis."
            action={
              <Button
                onClick={handleGenerateReport}
                loading={reportLoading}
                size="sm"
                variant="outline"
                className="mt-1"
              >
                {!reportLoading && <Play size={12} className="mr-1.5" />}
                Generate Now
              </Button>
            }
          />
        )}
      </div>

      {/* Full detail link */}
      <div className="pt-1 border-t border-[var(--border)]">
        <Link
          href={`/jobs/${job.id}`}
          className="inline-flex items-center gap-1 text-xs text-[var(--ink-muted)] hover:text-[var(--ink-primary)] transition-colors"
        >
          Open full detail
          <ExternalLink size={11} />
        </Link>
      </div>
    </div>
  );
}
