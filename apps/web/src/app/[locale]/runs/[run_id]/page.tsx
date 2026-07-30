import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import type { useTranslations } from "next-intl";
import { redirect } from "@/i18n/navigation";
import { getRun, getRunReport } from "@/api/client";
import type { RunRead, JobReportResponse, FitReportResponse } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DetailBackBar } from "@/components/ui/detail-back-bar";
import { fmtTs } from "@/lib/utils";
import { RunStatusStepper, type RunStatus } from "@/components/RunStatusStepper";
import { JobReportContent, type JobReportLabels } from "@/components/JobReportContent";
import { Building2, Compass, Workflow, ListChecks, StickyNote } from "lucide-react";
import { PageContainer } from "@/components/ui/page-container";

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
    return <Banner variant="info">{t("runInProgress")}</Banner>;
  }
  if (run.status === "queued") {
    return <Banner variant="neutral">{t("runQueuedMsg")}</Banner>;
  }
  if (run.status === "needs_review") {
    return <Banner variant="warn">{t("runNeedsReviewMsg")}</Banner>;
  }
  if (run.status === "failed") {
    return <Banner variant="danger">{t("runFailedMsg")}</Banner>;
  }
  if (run.status === "cancelled") {
    return <Banner variant="neutral">{t("runCancelledMsg")}</Banner>;
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

  // A finished fit report has exactly one canonical viewer — the decision page
  // at /fit-reports/[id] (gauge, composition bar, partial matches, positioning
  // tab). This route used to carry a second, thinner renderer of the same
  // payload; it now hands off instead. Non-succeeded fit_report runs still
  // render below (back bar + status banner).
  if (run.run_type === "fit_report" && run.status === "succeeded" && report !== null) {
    const locale = await getLocale();
    redirect({ href: `/fit-reports/${(report as FitReportResponse).id}`, locale });
  }

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
      <DetailBackBar
        backHref="/runs"
        backLabel={t("backToReports")}
        title={runLabel}
        meta={t("started", { time: fmtTs(run.created_at) })}
        right={
          <RunStatusStepper
            status={run.status as RunStatus}
            labels={{
              queued: t("statusQueued"),
              running: t("statusRunning"),
              done: t(STATUS_LABEL_KEYS[run.status] ?? "statusQueued"),
            }}
          />
        }
      />

      <div className="flex-1 overflow-y-auto">
        <PageContainer variant="wide" className="space-y-[var(--space-stack-lg)]">
          {/* Status message */}
          <StatusMessage run={run} t={t} />

          {/* Report viewer */}
          {report && run.run_type === "job_report" && (
            <JobReportSection report={report as JobReportResponse} t={t} tDetail={tDetail} />
          )}
        </PageContainer>
      </div>
    </>
  );
}
