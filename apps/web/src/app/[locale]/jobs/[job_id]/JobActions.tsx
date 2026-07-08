"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, archiveJob } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { Button } from "@/components/ui/button";
import { FileText, Trash2, PenLine } from "lucide-react";

/**
 * Split from a single JobActions bar into per-context pieces — the tab bar
 * shows only the action relevant to the active tab (report vs fit), Remove
 * is page-level so it renders separately and de-emphasized, and Tailor
 * Resume moves into the Fit tab itself (see JobDetailTabs' FitPanel), next
 * to the score it's actually reacting to.
 */

export function ReportActionButton({ jobId, hasExistingReport }: { jobId: string; hasExistingReport: boolean }) {
  const t = useTranslations("jobDetail");
  const router = useRouter();
  const getToken = useApiToken();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerateReport() {
    setLoading(true);
    setError(null);
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
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start job report run");
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button onClick={handleGenerateReport} loading={loading} size="sm" variant={hasExistingReport ? "outline" : "default"}>
        {!loading && <FileText size={15} className="mr-1.5" />}
        {hasExistingReport ? t("refreshReport") : t("generateReport")}
      </Button>
      {error && <span className="text-xs text-rose-600">{error}</span>}
    </div>
  );
}

export function TailorResumeButton({ jobId }: { jobId: string }) {
  const t = useTranslations("jobDetail");
  const router = useRouter();
  const getToken = useApiToken();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleTailor() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const run = await createRun({ run_type: "resume_tailor", input_snapshot: { job_id: jobId } }, token);
      const finished = await pollRunUntilDone(run.id, getToken);
      if (finished.status !== "succeeded") {
        throw new Error(finished.error_message ?? "Resume tailor failed");
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button onClick={handleTailor} loading={loading} size="sm">
        {!loading && <PenLine size={15} className="mr-1.5" />}
        {loading ? t("tailoring") : t("tailorResume")}
      </Button>
      {error && <span className="text-xs text-rose-600">{error}</span>}
    </div>
  );
}

/** Page-level (not tab-scoped), so it renders separated from + visually
 * quieter than whichever report action is showing next to it. */
export function RemoveJobButton({ jobId }: { jobId: string }) {
  const t = useTranslations("jobDetail");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const getToken = useApiToken();
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
    <Button
      onClick={handleArchive}
      loading={archiving}
      size="sm"
      variant="ghost"
      className="text-[var(--ink-faint)] hover:text-rose-500"
    >
      {!archiving && <Trash2 size={14} className="mr-1.5" />}
      {archiving ? tCommon("removing") : tCommon("remove")}
    </Button>
  );
}
