"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, getRunReport } from "@/api/client";
import { pollRunUntilDone, extractReportId } from "@/lib/pollRun";
import { Button } from "@/components/ui/button";
import { Loader2, Target, AlertCircle } from "lucide-react";

interface FitButtonProps {
  jobId: string;
  jobReportId?: string;
  force?: boolean;
  size?: "sm" | "md" | "lg";
  variant?: "default" | "outline" | "ghost";
  label?: string;
}

type UIState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; status: string }
  | { phase: "error"; message: string };

const POLL_INTERVAL_MS = 3000;

export function FitButton({
  jobId,
  jobReportId,
  force = false,
  size = "sm",
  variant = "default",
  label,
}: FitButtonProps) {
  const router = useRouter();
  const getToken = useApiToken();
  const [state, setState] = useState<UIState>({ phase: "idle" });
  const runIdRef = useRef<string | null>(null);

  const resolveReportId = useCallback(
    async (runId: string, token: string | null) => {
      const run = await pollRunUntilDone(runId, token, { intervalMs: POLL_INTERVAL_MS });
      if (run.status !== "succeeded") {
        throw new Error(run.error_message ?? `Fit analysis ${run.status.replace(/_/g, " ")}`);
      }
      let reportId = extractReportId(run);
      if (!reportId) {
        const report = await getRunReport(runId, token);
        reportId = report.id;
      }
      if (!reportId) {
        throw new Error("Fit report completed but no report ID returned");
      }
      return reportId;
    },
    [],
  );

  useEffect(() => {
    if (state.phase !== "polling" || !runIdRef.current) return;

    let cancelled = false;

    (async () => {
      try {
        const token = await getToken();
        const reportId = await resolveReportId(runIdRef.current!, token);
        if (!cancelled) {
          router.push(`/fit-reports/${reportId}`);
          router.refresh();
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            phase: "error",
            message: err instanceof Error ? err.message : "Fit report generation failed",
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [state.phase, getToken, resolveReportId, router]);

  async function handleClick() {
    setState({ phase: "submitting" });
    try {
      const token = await getToken();
      const run = await createRun(
        {
          run_type: "fit_report",
          input_snapshot: {
            job_id: jobId,
            job_report_id: jobReportId,
            force_refresh: force,
          },
        },
        token,
      );
      runIdRef.current = run.id;
      setState({ phase: "polling", status: run.status });
    } catch (err) {
      setState({
        phase: "error",
        message: err instanceof Error ? err.message : "Failed to start fit analysis",
      });
    }
  }

  if (state.phase === "error") {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 text-sm text-rose-600">
          <AlertCircle size={14} />
          <span className="text-xs">{state.message}</span>
        </div>
        <Button size="sm" variant="outline" onClick={() => setState({ phase: "idle" })}>
          Retry
        </Button>
      </div>
    );
  }

  if (state.phase === "polling" || state.phase === "submitting") {
    return (
      <Button size={size} variant={variant} disabled>
        <Loader2 size={14} className="animate-spin mr-1.5" />
        {state.phase === "submitting" ? "Starting…" : "Analyzing fit…"}
      </Button>
    );
  }

  return (
    <Button size={size} variant={variant} onClick={handleClick}>
      <Target size={14} className="mr-1.5" />
      {label ?? (force ? "Regenerate Fit Report" : "Analyze Fit")}
    </Button>
  );
}
