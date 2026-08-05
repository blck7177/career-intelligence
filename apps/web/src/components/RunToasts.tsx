"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { useRunFetcher, useRunOwnerId } from "@/hooks/useTrackedRun";
import { onRunSettled, rehydrateTracking, type SettledRun } from "@/lib/runTracker";
import { toast } from "@/components/ui/toaster";

/**
 * Says when a run finished, wherever you happen to be by then.
 *
 * Mounted once in the root layout rather than next to any button, because the
 * point is that the button need not still be there: a report you asked for from
 * the tracker's job modal can land while you are three views away.
 *
 * The wording lives here rather than in the store so that a run picked back up
 * after a page reload still gets a real sentence — the store remembers run ids,
 * not copy.
 */
function successMessage(t: ReturnType<typeof useTranslations>, runType: string): string | null {
  // Written out per type on purpose: the i18n key guard only sees string
  // literals inside t(), so a computed key would ship unguarded (see V6).
  switch (runType) {
    case "job_report":
      return t("toastReportDone");
    case "fit_report":
      return t("toastFitDone");
    case "resume_tailor":
      return t("toastTailorDone");
    default:
      return null;
  }
}

function failureMessage(t: ReturnType<typeof useTranslations>, runType: string): string | null {
  switch (runType) {
    case "job_report":
      return t("toastReportFailed");
    case "fit_report":
      return t("toastFitFailed");
    case "resume_tailor":
      return t("toastTailorFailed");
    default:
      return null;
  }
}

export function RunToasts() {
  const t = useTranslations("runs");
  const userId = useRunOwnerId();
  const fetchRun = useRunFetcher();

  // Reload recovery: a run started before F5 is still executing server-side.
  useEffect(() => {
    rehydrateTracking(userId, fetchRun);
  }, [userId, fetchRun]);

  useEffect(
    () =>
      onRunSettled((run: SettledRun) => {
        if (run.userId !== userId) return;
        if (run.status === "succeeded") {
          const message = successMessage(t, run.runType);
          if (message) toast.success(message);
          return;
        }
        const message = failureMessage(t, run.runType);
        if (message) toast.error(message, { description: run.errorMessage ?? undefined });
      }),
    [t, userId],
  );

  return null;
}
