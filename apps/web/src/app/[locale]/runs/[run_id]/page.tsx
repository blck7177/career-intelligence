import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import type { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { getRun, getRunReport } from "@/api/client";
import type { RunRead, JobReportResponse, FitReportResponse } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtTs } from "@/lib/utils";
import { ScoreBadge, SeverityChip } from "@/components/MatchVisuals";
import { RunStatusStepper, type RunStatus } from "@/components/RunStatusStepper";
import { JobReportContent, type JobReportLabels } from "@/components/JobReportContent";
import { Building2, Compass, Workflow, ListChecks, StickyNote } from "lucide-react";

const JOB_REPORT_ICONS = {
  businessContext: Building2,
  positionFunction: Compass,
  dailyWorkflow: Workflow,
  skillDemands: ListChecks,
  analystNotes: StickyNote,
};

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ run_id: string }>;
}

type T = ReturnType<typeof useTranslations>;

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
      <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)] p-4 text-sm text-[var(--ink-secondary)]">
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
      <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)] p-4 text-sm text-[var(--ink-muted)]">
        {t("runCancelledMsg")}
      </div>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Report viewer helpers
// ---------------------------------------------------------------------------

function JobReportSection({ report, t, tDetail }: { report: JobReportResponse; t: T; tDetail: T }) {
  const labels: JobReportLabels = {
    businessContext: tDetail("businessContext"),
    positionFunction: tDetail("positionFunction"),
    dailyWorkflow: tDetail("dailyWorkflow"),
    likelyInputs: tDetail("likelyInputs"),
    typicalAnalyses: tDetail("typicalAnalyses"),
    outputs: tDetail("outputs"),
    keySkillDemands: tDetail("keySkillDemands"),
    core: tDetail("importanceCore"),
    supporting: tDetail("importanceSupporting"),
    other: tDetail("importanceOther"),
    analystNotes: tDetail("analystNotes"),
    uncertaintyNotes: tDetail("uncertaintyNotes"),
    confidence: tDetail("confidenceLabel"),
    problemSolved: (text) => tDetail("problemSolved", { text }),
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          {t("runJobReport")}
          <Badge variant="match-strong" className="text-xs">{report.status}</Badge>
          {report.used_research && (
            <Badge variant="match-good" className="text-xs">{tDetail("withResearch")}</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <JobReportContent report={report} labels={labels} icons={JOB_REPORT_ICONS} />
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
          <Badge variant="match-strong" className="text-xs">{report.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-xs text-[var(--ink-secondary)]">
        {matchSummary && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-0.5">{t("summary")}</p>
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
            <p className="font-medium text-[var(--ink-muted)] mb-1">{t("strongMatches", { count: Math.min(strongMatches.length, 3) })}</p>
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
            <p className="font-medium text-[var(--ink-muted)] mb-1">{t("gaps")}</p>
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
            <p className="font-medium text-[var(--ink-muted)] mb-1">{t("riskFlags")}</p>
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
            <p className="font-medium text-[var(--ink-muted)] mb-1">{t("interviewTalkingPoints")}</p>
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
  const STATUS_LABEL_KEYS: Record<string, string> = {
    queued: "statusQueued",
    running: "statusRunning",
    succeeded: "statusSucceeded",
    failed: "statusFailed",
    needs_review: "statusNeedsReview",
    cancelled: "statusCancelled",
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
            <div>
              <h1 className="text-xl font-semibold capitalize" style={{ color: "var(--ink-primary)" }}>{runLabel}</h1>
              <p className="text-sm mt-0.5" style={{ color: "var(--muted-foreground)" }}>{t("started", { time: fmtTs(run.created_at) })}</p>
            </div>
            <RunStatusStepper
              status={run.status as RunStatus}
              labels={{
                queued: t("statusQueued"),
                running: t("statusRunning"),
                done: t(STATUS_LABEL_KEYS[run.status] ?? "statusQueued"),
              }}
            />
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
