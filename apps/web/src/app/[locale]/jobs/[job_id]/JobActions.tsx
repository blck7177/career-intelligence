"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, archiveJob } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { FitButton } from "@/components/FitButton";
import { Button } from "@/components/ui/button";
import { FileText, Trash2, PenLine } from "lucide-react";

interface JobActionsProps {
  jobId: string;
  hasExistingReport: boolean;
  jobReportId?: string;
  hasProfile?: boolean;
}

export function JobActions({ jobId, hasExistingReport, jobReportId, hasProfile }: JobActionsProps) {
  const t = useTranslations("jobDetail");
  const tJobs = useTranslations("jobs");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const getToken = useApiToken();
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [tailorLoading, setTailorLoading] = useState(false);
  const [tailorError, setTailorError] = useState<string | null>(null);

  async function handleGenerateReport() {
    setReportLoading(true);
    setReportError(null);
    try {
      const token = await getToken();
      const run = await createRun(
        {
          run_type: "job_report",
          input_snapshot: {
            job_id: jobId,
            use_research: false,
            force_refresh: hasExistingReport,
          },
        },
        token,
      );
      const finished = await pollRunUntilDone(run.id, getToken);
      if (finished.status !== "succeeded") {
        throw new Error(finished.error_message ?? "Job report generation failed");
      }
      router.refresh();
      setReportLoading(false);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Failed to start job report run");
      setReportLoading(false);
    }
  }

  const [archiving, setArchiving] = useState(false);

  async function handleArchive() {
    if (!confirm(t("confirmRemove"))) return;
    setArchiving(true);
    try {
      const token = await getToken();
      await archiveJob(jobId, token);
      router.push("/jobs");
    } catch {
      setArchiving(false);
    }
  }

  return (
    <div className="flex items-center gap-2.5">
      <Button
        onClick={handleGenerateReport}
        loading={reportLoading}
        size="sm"
        variant={hasExistingReport ? "outline" : "default"}
      >
        {!reportLoading && <FileText size={15} className="mr-1.5" />}
        {hasExistingReport ? t("refreshReport") : t("generateReport")}
      </Button>
      {reportError && <span className="text-xs text-rose-600">{reportError}</span>}

      <FitButton
        jobId={jobId}
        jobReportId={jobReportId}
        disabled={!hasExistingReport}
        variant={hasExistingReport ? "default" : "outline"}
        label={tJobs("analyzeFit")}
        inline
      />

      {hasProfile && hasExistingReport && (
        <Button
          onClick={async () => {
            setTailorLoading(true);
            setTailorError(null);
            try {
              const token = await getToken();
              const run = await createRun(
                { run_type: "resume_tailor", input_snapshot: { job_id: jobId } },
                token,
              );
              const finished = await pollRunUntilDone(run.id, getToken);
              if (finished.status !== "succeeded") {
                throw new Error(finished.error_message ?? "Resume tailor failed");
              }
              router.refresh();
            } catch (err) {
              setTailorError(err instanceof Error ? err.message : "Failed");
            } finally {
              setTailorLoading(false);
            }
          }}
          loading={tailorLoading}
          size="sm"
          variant="outline"
        >
          {!tailorLoading && <PenLine size={15} className="mr-1.5" />}
          {tailorLoading ? t("tailoring") : t("tailorResume")}
        </Button>
      )}
      {tailorError && <span className="text-xs text-rose-600">{tailorError}</span>}

      <Button
        onClick={handleArchive}
        loading={archiving}
        size="sm"
        variant="outline"
        className="text-[var(--ink-muted)] hover:text-rose-500 hover:border-rose-300"
      >
        {!archiving && <Trash2 size={15} className="mr-1.5" />}
        {archiving ? tCommon("removing") : tCommon("remove")}
      </Button>
    </div>
  );
}
