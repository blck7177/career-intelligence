"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { useRunFetcher, useRunOwnerId, useRunSettled, useTrackedRun } from "@/hooks/useTrackedRun";
import { createRun, getRunReport } from "@/api/client";
import { runKey, startTracking } from "@/lib/runTracker";
import { Button } from "@/components/ui/button";
import { Target, AlertCircle } from "lucide-react";

interface FitButtonProps {
  jobId: string;
  jobReportId?: string;
  force?: boolean;
  disabled?: boolean;
  size?: "sm" | "md" | "lg";
  variant?: "default" | "outline" | "ghost";
  label?: string;
  inline?: boolean;
  /** Called after a successful analysis, in addition to router.refresh() —
   * the master-detail pane fetches its own data client-side and won't see
   * that refresh, so it needs this explicit nudge. */
  onMutated?: () => void;
}

export function FitButton({
  jobId,
  jobReportId,
  force = false,
  disabled = false,
  size = "sm",
  variant = "default",
  label,
  inline = false,
  onMutated,
}: FitButtonProps) {
  const t = useTranslations("jobs");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const getToken = useApiToken();
  const userId = useRunOwnerId();
  const fetchRun = useRunFetcher();
  // Tracked outside this component: the same run is watched whether this button
  // is in the list, the detail pane, or a modal that gets closed mid-analysis.
  const key = runKey("fit_report", jobId);
  const tracked = useTrackedRun(key, userId);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Navigating away is a reply to *your* click, not to a run ending: this same
   *  job's button can be mounted in the list and the pane at once, and only the
   *  one that was pressed should move the page. Refreshing is idempotent, so
   *  that side is left unguarded. */
  const startedHere = useRef(false);

  useRunSettled(key, (run) => {
    if (run.status !== "succeeded") {
      startedHere.current = false;
      setError(run.errorMessage ?? `Fit analysis ${run.status.replace(/_/g, " ")}`);
      return;
    }
    setError(null);
    if (inline || !startedHere.current) {
      router.refresh();
      onMutated?.();
      startedHere.current = false;
      return;
    }
    startedHere.current = false;
    void (async () => {
      try {
        const report = await getRunReport(run.runId, await getToken());
        router.push(`/fit-reports/${report.id}`);
        router.refresh();
      } catch {
        // The analysis did succeed; only the jump to it failed. Stay put and
        // refresh so the new score shows up where the user already is.
        router.refresh();
        onMutated?.();
      }
    })();
  });

  async function handleClick() {
    if (disabled) return;
    setStarting(true);
    setError(null);
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
      startedHere.current = true;
      startTracking({ key, runId: run.id, runType: "fit_report", userId }, fetchRun);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start fit analysis");
    } finally {
      setStarting(false);
    }
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 text-sm text-rose-600">
          <AlertCircle size={14} />
          <span className="text-xs">{error}</span>
        </div>
        <Button size="sm" variant="outline" onClick={() => setError(null)}>
          {tCommon("retry")}
        </Button>
      </div>
    );
  }

  const busy = starting || tracked !== null;
  if (busy) {
    return (
      <Button size={size} variant={variant} loading>
        {t("analyzing")}
      </Button>
    );
  }

  return (
    <Button size={size} variant={variant} onClick={handleClick} disabled={disabled}>
      <Target size={14} className="mr-1.5" />
      {label ?? (force ? t("regenerateFit") : t("analyzeFit"))}
    </Button>
  );
}
