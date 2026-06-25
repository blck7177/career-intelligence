"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { FitButton } from "@/components/FitButton";
import { Button } from "@/components/ui/button";
import { Loader2, FileText, UserCheck } from "lucide-react";

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
      const finished = await pollRunUntilDone(run.id, token);
      if (finished.status !== "succeeded") {
        throw new Error(finished.error_message ?? "Job report generation failed");
      }
      router.push(`/jobs/${jobId}`);
      router.refresh();
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Failed to start job report run");
      setReportLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      {/* Job Intelligence Report */}
      <div className="space-y-1">
        <Button
          onClick={handleGenerateReport}
          disabled={reportLoading}
          size="sm"
          variant={hasExistingReport ? "outline" : "default"}
          className="w-full justify-start"
        >
          {reportLoading ? (
            <Loader2 size={13} className="animate-spin mr-2" />
          ) : (
            <FileText size={13} className="mr-2" />
          )}
          {hasExistingReport ? "Refresh Job Report" : "Generate Job Report"}
        </Button>
        {reportError && <p className="text-xs text-rose-600">{reportError}</p>}
      </div>

      {/* Candidate Fit Report */}
      <div className="space-y-1">
        <p className="text-xs text-zinc-500 flex items-center gap-1.5">
          <UserCheck size={12} />
          Uses your saved profile.{" "}
          <a href="/profile" className="underline hover:text-zinc-700">
            Edit profile
          </a>
        </p>
        <FitButton
          jobId={jobId}
          jobReportId={jobReportId}
          variant={hasExistingReport ? "default" : "outline"}
          label={hasExistingReport ? "Analyze Fit" : "Analyze Fit (needs report)"}
        />
        {!hasExistingReport && (
          <p className="text-[10px] text-zinc-400">Generate a job report first for best results.</p>
        )}
      </div>
    </div>
  );
}
