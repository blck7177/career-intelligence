"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createApplication } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ClipboardCheck, CalendarClock } from "lucide-react";

/**
 * Entry point from a job into the tracker: create an application (applied now,
 * or planned) for this job. Reuses createApplication; a duplicate (409) resolves
 * to the "already tracked" state instead of surfacing an error. Rendered inside
 * JobDetailTabs, so it appears on both the full job page and the desktop pane.
 */
export function MarkAppliedButton({ jobId, onMutated }: { jobId: string; onMutated?: () => void }) {
  const t = useTranslations("tracker");
  const router = useRouter();
  const getToken = useApiToken();
  const [busy, setBusy] = useState<"applied" | "planned" | null>(null);
  const [done, setDone] = useState<null | "created" | "exists">(null);
  const [error, setError] = useState<string | null>(null);

  async function create(status: "applied" | "planned") {
    setBusy(status);
    setError(null);
    try {
      const token = await getToken();
      await createApplication({ job_id: jobId, status }, token);
      setDone("created");
      router.refresh();
      onMutated?.();
    } catch (err) {
      if ((err as { status?: number })?.status === 409) {
        setDone("exists");
      } else {
        setError(err instanceof Error ? err.message : "Failed");
      }
    } finally {
      setBusy(null);
    }
  }

  if (done) {
    return (
      <span className="flex items-center gap-1.5 text-sm">
        <ClipboardCheck size={15} style={{ color: "var(--primary)" }} />
        <span style={{ color: "var(--ink-muted)" }}>
          {done === "created" ? t("tracked") : t("alreadyTracked")}
        </span>
        <Link href="/tracker" className="font-semibold hover:underline" style={{ color: "var(--primary)" }}>
          {t("viewInTracker")}
        </Link>
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Button onClick={() => create("applied")} loading={busy === "applied"} disabled={busy !== null} size="sm">
        {busy !== "applied" && <ClipboardCheck size={15} className="mr-1.5" />}
        {t("markApplied")}
      </Button>
      <Button
        onClick={() => create("planned")}
        loading={busy === "planned"}
        disabled={busy !== null}
        size="sm"
        variant="outline"
      >
        {busy !== "planned" && <CalendarClock size={15} className="mr-1.5" />}
        {t("planToApply")}
      </Button>
      {error && <span className="text-xs text-rose-600">{error}</span>}
    </div>
  );
}
