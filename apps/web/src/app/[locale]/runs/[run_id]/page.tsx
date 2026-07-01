import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import type { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { getRun, getRunReport } from "@/api/client";
import type { RunRead, JobReportResponse, FitReportResponse } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, CheckCircle2, XCircle, Circle, AlertCircle, Clock } from "lucide-react";
import { fmtTs, statusBg } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ run_id: string }>;
}

type T = ReturnType<typeof useTranslations>;

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={14} className="text-rose-500" />;
  if (status === "needs_review") return <AlertCircle size={14} className="text-amber-500" />;
  if (status === "running") return <Circle size={14} className="text-blue-500 animate-pulse" />;
  if (status === "cancelled") return <Circle size={14} className="text-zinc-400" />;
  return <Clock size={14} className="text-zinc-400" />;
}

function StatusMessage({ run, t }: { run: RunRead; t: T }) {
  if (run.status === "running") {
    return (
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">
        {t("runInProgress")}
      </div>
    );
  }
  if (run.status === "queued") {
    return (
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-600">
        {t("runQueuedMsg")}
      </div>
    );
  }
  if (run.status === "needs_review") {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
        {t("runNeedsReviewMsg")}
      </div>
    );
  }
  if (run.status === "failed") {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        {t("runFailedMsg")}
      </div>
    );
  }
  if (run.status === "cancelled") {
    return (
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-500">
        {t("runCancelledMsg")}
      </div>
    );
  }
  return null;
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

function JobReportSection({ report, t, tDetail }: { report: JobReportResponse; t: T; tDetail: T }) {
  const s = report.structured_json as Record<string, unknown>;

  const primaryRoleCategory = s.primary_role_category as string | undefined;

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
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          {t("runJobReport")}
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
          {report.used_research && (
            <Badge className="bg-blue-100 text-blue-700 text-xs">{tDetail("withResearch")}</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-zinc-700">
        {primaryRoleCategory && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">{t("roleCategory")}</p>
            <p>{primaryRoleCategory}</p>
          </div>
        )}

        {bc?.summary && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">{tDetail("businessContext")}</p>
            <p className="leading-relaxed">{bc.summary}</p>
            {bc.problem_solved && (
              <p className="leading-relaxed text-zinc-500 mt-0.5">{tDetail("problemSolved", { text: bc.problem_solved })}</p>
            )}
          </div>
        )}

        {pf?.primary_function && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">{tDetail("positionFunction")}</p>
            <p className="leading-relaxed font-medium">{pf.primary_function}</p>
            {pf.function_mix_description && (
              <p className="leading-relaxed text-zinc-500 mt-0.5">{pf.function_mix_description}</p>
            )}
          </div>
        )}

        {dw && (dw.likely_analyses?.length || dw.likely_outputs?.length) ? (
          <div>
            <p className="font-medium text-zinc-500 mb-1">{tDetail("dailyWorkflow")}</p>
            {dw.likely_analyses && dw.likely_analyses.length > 0 && (
              <div className="mb-1">
                <p className="text-zinc-400 mb-0.5">{t("analyses")}</p>
                <ul className="space-y-0.5 list-disc list-inside">
                  {dw.likely_analyses.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            )}
            {dw.likely_outputs && dw.likely_outputs.length > 0 && (
              <div>
                <p className="text-zinc-400 mb-0.5">{t("outputs")}</p>
                <ul className="space-y-0.5 list-disc list-inside">
                  {dw.likely_outputs.map((o, i) => <li key={i}>{o}</li>)}
                </ul>
              </div>
            )}
          </div>
        ) : null}

        {demands && demands.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">{tDetail("keySkillDemands")}</p>
            <ul className="space-y-1">
              {demands.slice(0, 5).map((d, i) => (
                <li key={i} className="flex gap-2 items-start">
                  <span className={`shrink-0 rounded px-1 py-0.5 text-xs font-medium ${
                    d.importance === "core"
                      ? "bg-rose-100 text-rose-700"
                      : d.importance === "supporting"
                      ? "bg-amber-100 text-amber-700"
                      : "bg-zinc-100 text-zinc-600"
                  }`}>{d.importance ?? "—"}</span>
                  <span>
                    <span className="font-medium">{d.jd_phrase}</span>
                    {d.underlying_capability && (
                      <span className="text-zinc-500"> — {d.underlying_capability}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {uncertaintyNotes && uncertaintyNotes.length > 0 && (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="font-medium text-amber-700 mb-1">{tDetail("uncertaintyNotes")}</p>
            <ul className="space-y-1">
              {uncertaintyNotes.map((n, i) => (
                <li key={i}>
                  <span className="font-medium text-amber-700">{n.issue}</span>
                  {n.impact && <span className="text-amber-600"> — {n.impact}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FitReportSection({ report, t }: { report: FitReportResponse; t: T }) {
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
          {t("candidateFitReport")}
          <ScoreBadge score={report.overall_match_score} />
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-xs text-zinc-700">
        {matchSummary && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">{t("summary")}</p>
            <p className="leading-relaxed">{matchSummary}</p>
          </div>
        )}

        {nextAction && (
          <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 flex items-center gap-2">
            <p className="font-medium text-blue-700">{t("recommendedAction")}</p>
            <p className="text-blue-700 font-semibold">{nextAction}</p>
          </div>
        )}

        {strongMatches.length > 0 && (
          <div>
            <p className="font-medium text-zinc-500 mb-1">{t("strongMatches", { count: Math.min(strongMatches.length, 3) })}</p>
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
            <p className="font-medium text-zinc-500 mb-1">{t("gaps")}</p>
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
            <p className="font-medium text-zinc-500 mb-1">{t("riskFlags")}</p>
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
            <p className="font-medium text-zinc-500 mb-1">{t("interviewTalkingPoints")}</p>
            <ol className="space-y-0.5 list-decimal list-inside">
              {talkingPoints.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default async function RunDetailPage({ params }: PageProps) {
  const { run_id } = await params;

  const token = await getServerToken();
  const t = await getTranslations("runs");
  const tDetail = await getTranslations("jobDetail");

  let run: RunRead;
  try {
    run = await getRun(run_id, token);
  } catch {
    notFound();
  }

  const isReportRun = run.run_type === "job_report" || run.run_type === "fit_report";
  const report = isReportRun && run.status === "succeeded"
    ? await getRunReport(run_id, token).catch(() => null)
    : null;

  const RUN_TYPE_KEYS: Record<string, string> = {
    job_discovery: "runDiscovery",
    job_report: "runJobReport",
    fit_report: "runFitReport",
  };
  const runLabel = t(RUN_TYPE_KEYS[run.run_type] ?? "runDiscovery");

  return (
    <>
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Link
          href="/runs"
          className="text-[13px] hover:underline"
          style={{ color: "var(--primary)" }}
        >
          {t("backToReports")}
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-7 py-6 space-y-6">
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <StatusIcon status={run.status} />
              <div>
                <h1 className="text-xl font-semibold capitalize" style={{ color: "oklch(16% 0.015 275)" }}>{runLabel}</h1>
                <p className="text-sm mt-0.5" style={{ color: "var(--muted-foreground)" }}>{t("started", { time: fmtTs(run.created_at) })}</p>
              </div>
            </div>
            <Badge className={statusBg(run.status) + " text-sm px-3 py-1"}>
              {run.status.replace(/_/g, " ")}
            </Badge>
          </div>

          {/* Status message */}
          <StatusMessage run={run} t={t} />

          {/* Report viewer */}
          {report && run.run_type === "job_report" && (
            <JobReportSection report={report as JobReportResponse} t={t} tDetail={tDetail} />
          )}
          {report && run.run_type === "fit_report" && (
            <FitReportSection report={report as FitReportResponse} t={t} />
          )}
        </div>
      </div>
    </>
  );
}
