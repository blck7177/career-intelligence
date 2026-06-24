import Link from "next/link";
import { notFound } from "next/navigation";
import { getJob, getLatestJobReport } from "@/api/client";
import type { JobRead, JobReportResponse } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, Building2, MapPin, ExternalLink, Globe, ChevronRight } from "lucide-react";
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

function jobStatusLabel(status: string): string {
  const MAP: Record<string, string> = {
    reportable: "Report Ready",
    discovered: "Needs Report",
    stale: "Stale",
    invalid: "Invalid",
  };
  return MAP[status] ?? status;
}

// ---------------------------------------------------------------------------
// Report sections
// ---------------------------------------------------------------------------

function SeverityChip({ severity }: { severity: string }) {
  const color =
    severity === "blocking" ? "bg-rose-100 text-rose-700"
    : severity === "significant" ? "bg-amber-100 text-amber-700"
    : "bg-zinc-100 text-zinc-600";
  return <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>{severity}</span>;
}

function JobIntelligenceReport({ report }: { report: JobReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;

  const primaryWorkstream = s.primary_workstream as string | undefined;
  const bc = s.business_context as
    | { summary?: string; problem_solved?: string; confidence?: string }
    | undefined;
  const pf = s.position_function as
    | { primary_function?: string; function_mix_description?: string; confidence?: string }
    | undefined;
  const dw = s.daily_workflow as
    | { likely_inputs?: string[]; likely_analyses?: string[]; likely_outputs?: string[] }
    | undefined;
  const demands = s.underlying_skill_demands as
    | { jd_phrase?: string; underlying_capability?: string; importance?: string }[]
    | undefined;
  const uncertaintyNotes = s.uncertainty_notes as
    | { issue?: string; impact?: string }[]
    | undefined;

  return (
    <div className="space-y-5">
      {/* Title bar */}
      <div className="flex items-center gap-2 pb-3 border-b border-zinc-100">
        <h2 className="text-base font-semibold text-zinc-800">Job Intelligence Report</h2>
        {report.used_research && (
          <Badge className="bg-blue-100 text-blue-700 text-[10px]">with research</Badge>
        )}
        <Badge className="bg-emerald-100 text-emerald-700 text-[10px]">{report.status}</Badge>
      </div>

      {primaryWorkstream && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">
            Primary Workstream
          </p>
          <p className="text-sm font-medium text-zinc-800">{primaryWorkstream}</p>
        </div>
      )}

      {bc?.summary && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">
            Business Context
          </p>
          <p className="text-sm text-zinc-700 leading-relaxed">{bc.summary}</p>
          {bc.problem_solved && (
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
              Problem solved: {bc.problem_solved}
            </p>
          )}
        </div>
      )}

      {pf?.primary_function && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">
            Position Function
          </p>
          <p className="text-sm font-semibold text-zinc-800">{pf.primary_function}</p>
          {pf.function_mix_description && (
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{pf.function_mix_description}</p>
          )}
        </div>
      )}

      {dw && (dw.likely_analyses?.length || dw.likely_outputs?.length) ? (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
            Daily Workflow
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {dw.likely_analyses && dw.likely_analyses.length > 0 && (
              <div>
                <p className="text-xs font-medium text-zinc-500 mb-1.5">Typical Analyses</p>
                <ul className="space-y-1">
                  {dw.likely_analyses.map((a, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-zinc-600">
                      <ChevronRight size={11} className="text-zinc-300 shrink-0 mt-0.5" />
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {dw.likely_outputs && dw.likely_outputs.length > 0 && (
              <div>
                <p className="text-xs font-medium text-zinc-500 mb-1.5">Outputs</p>
                <ul className="space-y-1">
                  {dw.likely_outputs.map((o, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-zinc-600">
                      <ChevronRight size={11} className="text-zinc-300 shrink-0 mt-0.5" />
                      {o}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {demands && demands.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
            Key Skill Demands
          </p>
          <ul className="space-y-2">
            {demands.slice(0, 6).map((d, i) => (
              <li key={i} className="flex gap-2 items-start text-xs">
                <span className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${
                  d.importance === "core"
                    ? "bg-rose-100 text-rose-700"
                    : d.importance === "supporting"
                    ? "bg-amber-100 text-amber-700"
                    : "bg-zinc-100 text-zinc-600"
                }`}>{d.importance ?? "—"}</span>
                <span className="text-zinc-700">
                  <span className="font-medium">{d.jd_phrase}</span>
                  {d.underlying_capability && (
                    <span className="text-zinc-400"> — {d.underlying_capability}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {uncertaintyNotes && uncertaintyNotes.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold text-amber-700 mb-2">Uncertainty Notes</p>
          <ul className="space-y-1">
            {uncertaintyNotes.map((n, i) => (
              <li key={i} className="text-xs">
                <span className="font-medium text-amber-700">{n.issue}</span>
                {n.impact && <span className="text-amber-600"> — {n.impact}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function JobDetailPage({ params }: PageProps) {
  const { job_id } = await params;
  const token = await getServerToken();

  let job: JobRead;
  try {
    job = await getJob(job_id, token);
  } catch {
    notFound();
  }

  const report = await getLatestJobReport(job_id, token).catch(() => null);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Back */}
      <Link
        href="/jobs"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Role Inbox
      </Link>

      {/* Header */}
      <div className="space-y-1.5">
        <div className="flex items-start gap-2.5 flex-wrap">
          <h1 className="text-xl font-bold text-zinc-900 leading-tight">{job.title}</h1>
          <Badge className={jobStatusBg(job.status) + " text-xs mt-0.5 shrink-0"}>
            {jobStatusLabel(job.status)}
          </Badge>
        </div>
        <div className="flex items-center gap-4 text-sm text-zinc-500 flex-wrap">
          <span className="flex items-center gap-1.5">
            <Building2 size={13} />
            {job.company}
          </span>
          {job.location && (
            <span className="flex items-center gap-1.5">
              <MapPin size={13} />
              {job.location}
            </span>
          )}
          <a
            href={job.canonical_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline transition-colors"
          >
            <Globe size={11} />
            View posting
            <ExternalLink size={10} />
          </a>
        </div>
      </div>

      {/* Main content: report (2/3) + sidebar (1/3) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">

        {/* Left (2/3): Job Intelligence Report */}
        <div className="md:col-span-2">
          {report ? (
            <Card>
              <CardContent className="pt-5 pb-6 px-6">
                <JobIntelligenceReport report={report} />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-14 text-center space-y-2">
                <p className="text-sm font-medium text-zinc-500">No Job Intelligence Report yet</p>
                <p className="text-xs text-zinc-400">
                  Use &ldquo;Generate Job Report&rdquo; to analyze this role.
                </p>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right (1/3): Actions + metadata */}
        <div className="space-y-4">
          {/* Actions */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Actions</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <JobActions jobId={job_id} hasExistingReport={!!report} />
            </CardContent>
          </Card>

          {/* Metadata (condensed) */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-zinc-500">Details</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-1.5">
              {[
                { label: "Source", value: job.source_type },
                { label: "Discovered", value: fmtTs(job.created_at.toString()) },
                { label: "Last seen", value: job.last_seen_at ? fmtTs(job.last_seen_at.toString()) : null },
              ].map(({ label, value }) =>
                value ? (
                  <div key={label} className="flex gap-2 text-xs">
                    <span className="w-20 shrink-0 text-zinc-400">{label}</span>
                    <span className="text-zinc-600 break-all">{value}</span>
                  </div>
                ) : null,
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
