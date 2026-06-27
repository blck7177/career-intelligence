"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { FitButton } from "@/components/FitButton";
import { Button } from "@/components/ui/button";
import { Loader2, FileText } from "lucide-react";

interface JobActionsProps {
  jobId: string;
  hasExistingReport: boolean;
  jobReportId?: string;
}

export function JobActions({ jobId, hasExistingReport, jobReportId }: JobActionsProps) {
  const router = useRouter();
  const getToken = useApiToken();
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

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

  return (
    <div className="flex items-center gap-2">
      <Button
        onClick={handleGenerateReport}
        disabled={reportLoading}
        size="sm"
        variant={hasExistingReport ? "outline" : "default"}
      >
        {reportLoading ? (
          <Loader2 size={13} className="animate-spin mr-1.5" />
        ) : (
          <FileText size={13} className="mr-1.5" />
        )}
        {hasExistingReport ? "Refresh Report" : "Generate Report"}
      </Button>
      {reportError && <span className="text-xs text-rose-600">{reportError}</span>}

      <FitButton
        jobId={jobId}
        jobReportId={jobReportId}
        disabled={!hasExistingReport}
        variant={hasExistingReport ? "default" : "outline"}
        label={hasExistingReport ? "Analyze Fit" : "Analyze Fit"}
        inline
      />
    </div>
  );
}
