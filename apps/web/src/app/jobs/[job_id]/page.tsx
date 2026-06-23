import Link from "next/link";
import { notFound } from "next/navigation";
import { getJob, getLatestJobReport } from "@/api/client";
import type { JobRead, JobReportResponse } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, Building2, MapPin, ExternalLink, Globe } from "lucide-react";
import { fmtTs } from "@/lib/utils";
import { JobActions } from "./JobActions";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ job_id: string }>;
}

function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-emerald-100 text-emerald-800";
  if (status === "discovered") return "bg-blue-100 text-blue-800";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  if (status === "stale") return "bg-zinc-100 text-zinc-600";
  return "bg-zinc-100 text-zinc-600";
}

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 80 ? "bg-emerald-100 text-emerald-700"
    : score >= 60 ? "bg-amber-100 text-amber-700"
    : "bg-rose-100 text-rose-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {score}/100
    </span>
  );
}

function SeverityChip({ severity }: { severity: string }) {
  const color =
    severity === "blocking" ? "bg-rose-100 text-rose-700"
    : severity === "significant" ? "bg-amber-100 text-amber-700"
    : "bg-zinc-100 text-zinc-600";
  return <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>{severity}</span>;
}

function JobReportSection({ report }: { report: JobReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
          Job Intelligence Report
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
          {report.used_research && <Badge className="bg-blue-100 text-blue-700 text-xs">with research</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-zinc-700">
        {(s.primary_workstream as string | undefined) && (
          <div><p className="font-medium text-zinc-500 mb-0.5">Primary Workstream</p><p>{s.primary_workstream as string}</p></div>
        )}
        {(s.business_context as string | undefined) && (
          <div><p className="font-medium text-zinc-500 mb-0.5">Business Context</p><p className="leading-relaxed">{s.business_context as string}</p></div>
        )}
        {(s.position_function as string | undefined) && (
          <div><p className="font-medium text-zinc-500 mb-0.5">Position Function</p><p className="leading-relaxed">{s.position_function as string}</p></div>
        )}
        {(s.uncertainty_notes as string | undefined) && (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="font-medium text-amber-700 mb-0.5">Uncertainty Notes</p>
            <p className="text-amber-700">{s.uncertainty_notes as string}</p>
          </div>
        )}
        <p className="text-zinc-400 pt-1">Report ID: {report.id} · v{report.prompt_version}</p>
      </CardContent>
    </Card>
  );
}

export default async function JobDetailPage({ params }: PageProps) {
  const { job_id } = await params;

  let job: JobRead;
  try {
    job = await getJob(job_id);
  } catch {
    notFound();
  }

  const report = await getLatestJobReport(job_id).catch(() => null);

  const metaFields: { label: string; value: string | null | undefined }[] = [
    { label: "Source type", value: job.source_type },
    { label: "Discovered", value: fmtTs(job.created_at.toString()) },
    { label: "Last seen", value: job.last_seen_at ? fmtTs(job.last_seen_at.toString()) : null },
    { label: "Discovery run", value: job.discovered_run_id },
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Back */}
      <Link href="/jobs" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900">
        <ArrowLeft size={14} /> Back to Jobs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold">{job.title}</h1>
            <Badge className={jobStatusBg(job.status) + " text-xs"}>{job.status}</Badge>
          </div>
          <div className="flex items-center gap-3 text-sm text-zinc-500 flex-wrap">
            <span className="flex items-center gap-1"><Building2 size={13} />{job.company}</span>
            {job.location && <span className="flex items-center gap-1"><MapPin size={13} />{job.location}</span>}
          </div>
          <a
            href={job.canonical_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
          >
            <Globe size={11} />
            View job posting
            <ExternalLink size={10} />
          </a>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Left: metadata + actions */}
        <div className="space-y-4">
          {/* Metadata */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Database Metadata</CardTitle></CardHeader>
            <CardContent className="space-y-1.5">
              {metaFields.map(({ label, value }) =>
                value ? (
                  <div key={label} className="flex gap-2 text-xs">
                    <span className="w-28 shrink-0 text-zinc-400">{label}</span>
                    <span className="text-zinc-700 font-mono break-all">{value}</span>
                  </div>
                ) : null,
              )}
              <div className="flex gap-2 text-xs">
                <span className="w-28 shrink-0 text-zinc-400">Report</span>
                <span className={report ? "text-emerald-600 font-medium" : "text-zinc-400"}>
                  {report ? "Available" : "Not generated"}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Actions */}
          <Card>
            <CardContent className="pt-4">
              <JobActions jobId={job_id} hasExistingReport={!!report} />
            </CardContent>
          </Card>
        </div>

        {/* Right: report if available, else placeholder */}
        <div className="md:col-span-2 space-y-4">
          {report ? (
            <JobReportSection report={report} />
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-zinc-300 py-16 gap-2 text-center">
              <p className="text-sm font-medium text-zinc-500">No Job Intelligence Report yet</p>
              <p className="text-xs text-zinc-400">
                Use "Generate Job Report" to analyze this role.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
