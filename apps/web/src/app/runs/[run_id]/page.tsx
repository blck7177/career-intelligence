import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun, listTasks, listEvents, listAgentInvocations, getRunReport } from "@/api/client";
import type { RunRead, TaskRead, TaskEventRead, AgentInvocationRead, JobReportResponse, FitReportResponse } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, CheckCircle2, XCircle, Circle, AlertCircle, Clock } from "lucide-react";
import { fmtTs, statusBg } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ run_id: string }>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={14} className="text-rose-500" />;
  if (status === "needs_review") return <AlertCircle size={14} className="text-amber-500" />;
  if (status === "running") return <Circle size={14} className="text-blue-500 animate-pulse" />;
  return <Circle size={14} className="text-zinc-400" />;
}

function TaskRow({ task }: { task: TaskRead }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-100 last:border-0">
      <div className="flex items-center gap-2">
        <StatusIcon status={task.status} />
        <div>
          <p className="text-xs font-medium">{task.task_type}</p>
          <p className="text-xs text-zinc-500">
            attempt {task.attempt_count}/{task.max_attempts}
            {task.started_at && ` · started ${fmtTs(task.started_at)}`}
          </p>
        </div>
      </div>
      <Badge className={statusBg(task.status) + " text-xs"}>{task.status}</Badge>
    </div>
  );
}

function EventRow({ event }: { event: TaskEventRead }) {
  return (
    <div className="flex gap-3 py-2 border-b border-zinc-100 last:border-0">
      <Clock size={12} className="text-zinc-400 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-xs font-medium text-zinc-700">{event.event_type}</p>
        {event.message && <p className="text-xs text-zinc-500 mt-0.5">{event.message}</p>}
        <p className="text-xs text-zinc-400 mt-0.5">{fmtTs(event.created_at)}</p>
      </div>
    </div>
  );
}

function AgentRow({ inv }: { inv: AgentInvocationRead }) {
  const dur =
    inv.started_at && inv.finished_at
      ? `${Math.round((new Date(inv.finished_at).getTime() - new Date(inv.started_at).getTime()) / 1000)}s`
      : null;

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-100 last:border-0">
      <div className="flex items-center gap-2">
        <StatusIcon status={inv.status} />
        <div>
          <p className="text-xs font-medium">{inv.agent_id}</p>
          <p className="text-xs text-zinc-500">
            {inv.skill_contract_version}
            {dur && ` · ${dur}`}
            {inv.exit_code != null && ` · exit ${inv.exit_code}`}
          </p>
        </div>
      </div>
      <Badge className={statusBg(inv.status) + " text-xs"}>{inv.status}</Badge>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report viewer helpers
// ---------------------------------------------------------------------------

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 80
      ? "bg-emerald-100 text-emerald-700"
      : score >= 60
      ? "bg-amber-100 text-amber-700"
      : "bg-rose-100 text-rose-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {score}/100
    </span>
  );
}

function SeverityChip({ severity }: { severity: string }) {
  const color =
    severity === "blocking"
      ? "bg-rose-100 text-rose-700"
      : severity === "significant"
      ? "bg-amber-100 text-amber-700"
      : "bg-zinc-100 text-zinc-600";
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
      {severity}
    </span>
  );
}

function JobReportSection({ report }: { report: JobReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  const primaryWorkstream = s.primary_workstream as string | undefined;
  const businessContext = s.business_context as string | undefined;
  const positionFunction = s.position_function as string | undefined;
  const uncertaintyNotes = s.uncertainty_notes as string | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Job Intelligence Report
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
          {report.used_research && (
            <Badge className="bg-blue-100 text-blue-700 text-xs">with research</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-zinc-700">
        {primaryWorkstream && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Primary Workstream</p>
            <p>{primaryWorkstream}</p>
          </div>
        )}
        {businessContext && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Business Context</p>
            <p className="leading-relaxed">{businessContext}</p>
          </div>
        )}
        {positionFunction && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Position Function</p>
            <p className="leading-relaxed">{positionFunction}</p>
          </div>
        )}
        {uncertaintyNotes && (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="font-medium text-amber-700 mb-0.5">Uncertainty Notes</p>
            <p className="text-amber-700">{uncertaintyNotes}</p>
          </div>
        )}
        <p className="text-zinc-400 pt-1">Report ID: {report.id} · v{report.prompt_version}</p>
      </CardContent>
    </Card>
  );
}

function FitReportSection({ report }: { report: FitReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  const matchSummary = s.match_summary as string | undefined;
  const strongMatches = (s.strong_matches as { demand: string; evidence: string }[]) ?? [];
  const gaps = (s.gaps as { demand: string; gap_description: string; severity: string }[]) ?? [];
  const riskFlags = (s.risk_flags as string[]) ?? [];
  const talkingPoints = (s.interview_talking_points as string[]) ?? [];
  const nextAction = s.recommended_next_action as string | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Candidate Fit Report
          <ScoreBadge score={report.overall_match_score} />
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-xs text-zinc-700">
        {matchSummary && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Summary</p>
            <p className="leading-relaxed">{matchSummary}</p>
          </div>
        )}

        {nextAction && (
          <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 flex items-center gap-2">
            <p className="font-medium text-blue-700">Recommended action:</p>
            <p className="text-blue-700 font-semibold">{nextAction}</p>
          </div>
        )}

        {strongMatches.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">Strong Matches (top {Math.min(strongMatches.length, 3)})</p>
            <ul className="space-y-1">
              {strongMatches.slice(0, 3).map((m, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-emerald-500 shrink-0">✓</span>
                  <span><span className="font-medium">{m.demand}</span> — {m.evidence}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {gaps.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">Gaps</p>
            <ul className="space-y-1.5">
              {gaps.map((g, i) => (
                <li key={i} className="flex gap-2 items-start">
                  <SeverityChip severity={g.severity} />
                  <span><span className="font-medium">{g.demand}</span> — {g.gap_description}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {riskFlags.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">Risk Flags</p>
            <ul className="space-y-0.5">
              {riskFlags.map((f, i) => (
                <li key={i} className="flex gap-1.5 items-start text-amber-700">
                  <span>⚠</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {talkingPoints.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">Interview Talking Points</p>
            <ol className="space-y-0.5 list-decimal list-inside">
              {talkingPoints.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}

        <p className="text-zinc-400 pt-1">
          Report ID: {report.id} · Job Report: {report.job_report_id} · v{report.prompt_version}
        </p>
      </CardContent>
    </Card>
  );
}

export default async function RunDetailPage({ params }: PageProps) {
  const { run_id } = await params;

  let run: RunRead;
  try {
    run = await getRun(run_id);
  } catch {
    notFound();
  }

  const isReportRun = run.run_type === "job_report" || run.run_type === "fit_report";

  const [tasks, events, invocations, report] = await Promise.all([
    listTasks(run_id).catch(() => [] as TaskRead[]),
    listEvents(run_id).catch(() => [] as TaskEventRead[]),
    listAgentInvocations(run_id).catch(() => [] as AgentInvocationRead[]),
    isReportRun && run.status === "succeeded"
      ? getRunReport(run_id).catch(() => null)
      : Promise.resolve(null),
  ]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Back */}
      <Link
        href="/runs"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900"
      >
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold font-mono">{run_id}</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {run.run_type.replace("_", " ")} · created {fmtTs(run.created_at)}
          </p>
        </div>
        <Badge className={statusBg(run.status) + " text-sm px-3 py-1"}>
          {run.status.replace("_", " ")}
        </Badge>
      </div>

      {run.error_message && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          <strong>{run.error_code}</strong>: {run.error_message}
        </div>
      )}

      {/* Three-column grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Tasks */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Tasks ({tasks.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {tasks.length === 0 ? (
              <p className="text-xs text-zinc-500">No tasks yet.</p>
            ) : (
              tasks.map((t) => <TaskRow key={t.id} task={t} />)
            )}
          </CardContent>
        </Card>

        {/* Events */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">Events ({events.length})</CardTitle>
          </CardHeader>
          <CardContent className="max-h-80 overflow-y-auto">
            {events.length === 0 ? (
              <p className="text-xs text-zinc-500">No events yet.</p>
            ) : (
              events.map((e) => <EventRow key={e.id} event={e} />)
            )}
          </CardContent>
        </Card>
      </div>

      {/* Report viewer */}
      {report && run.run_type === "job_report" && (
        <JobReportSection report={report as JobReportResponse} />
      )}
      {report && run.run_type === "fit_report" && (
        <FitReportSection report={report as FitReportResponse} />
      )}

      {/* Agent Invocations */}
      {invocations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Agent Invocations ({invocations.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {invocations.map((inv) => (
              <AgentRow key={inv.id} inv={inv} />
            ))}
          </CardContent>
        </Card>
      )}

      {/* Raw JSON (dev only) */}
      <details className="text-xs">
        <summary className="cursor-pointer text-zinc-400 hover:text-zinc-600">
          Raw run data
        </summary>
        <pre className="mt-2 overflow-auto rounded-lg bg-zinc-50 p-4 text-zinc-600 max-h-64">
          {JSON.stringify(run, null, 2)}
        </pre>
      </details>
    </div>
  );
}
