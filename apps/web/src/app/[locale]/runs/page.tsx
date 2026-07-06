import { getTranslations } from "next-intl/server";
import { ListChecks } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { StartRunButton } from "./StartRunButton";
import { fmtTs } from "@/lib/utils";
import { RunStatusStepper, type RunStatus } from "@/components/RunStatusStepper";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";

const RUN_TYPE_KEYS: Record<string, string> = {
  job_discovery: "runDiscovery",
  job_report: "runJobReport",
  fit_report: "runFitReport",
};

const STATUS_KEYS: Record<string, string> = {
  queued: "statusQueued",
  running: "statusRunning",
  succeeded: "statusSucceeded",
  failed: "statusFailed",
  needs_review: "statusNeedsReview",
  cancelled: "statusCancelled",
};

function statusBadgeStyle(status: string): { bg: string; fg: string } {
  if (status === "succeeded") return { bg: "var(--match-strong-bg)", fg: "var(--match-strong-fg)" };
  if (status === "running") return { bg: "var(--secondary)", fg: "var(--secondary-foreground)" };
  if (status === "failed") return { bg: "oklch(95% 0.02 25)", fg: "oklch(45% 0.15 25)" };
  if (status === "needs_review") return { bg: "oklch(95% 0.03 80)", fg: "oklch(45% 0.12 80)" };
  return { bg: "var(--muted)", fg: "var(--muted-foreground)" };
}

function RunRow({ run, t }: { run: RunRead; t: (key: string) => string }) {
  const badge = statusBadgeStyle(run.status);
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex items-center justify-between gap-4 bg-white rounded-[10px] p-4 transition-shadow hover:shadow-md"
      style={{ border: "1px solid var(--border)", boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)" }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <RunStatusStepper status={run.status as RunStatus} size="sm" />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate" style={{ color: "var(--ink-primary)" }}>
            {t(RUN_TYPE_KEYS[run.run_type] ?? "runDiscovery")}
          </p>
          <p className="text-xs mt-0.5" style={{ color: "var(--ink-faint)" }}>{fmtTs(run.created_at)}</p>
        </div>
      </div>
      <span
        className="text-xs font-medium px-2.5 py-1 rounded-full shrink-0"
        style={{ background: badge.bg, color: badge.fg }}
      >
        {t(STATUS_KEYS[run.status] ?? "statusQueued")}
      </span>
    </Link>
  );
}

export default async function RunsPage() {
  const t = await getTranslations("runs");
  let runs: RunRead[] = [];
  let fetchError: string | null = null;

  try {
    const token = await getServerToken();
    const list = await listRuns(token);
    runs = list.items;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load runs";
  }

  const discoveryRuns = runs.filter((r) => r.run_type === "job_discovery");
  const reportRuns = runs.filter((r) => r.run_type !== "job_discovery");

  return (
    <>
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
          {t("title")}
        </span>
        <span className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          {t("runCount", { count: runs.length })}
        </span>
        <div className="flex-1" />
        <StartRunButton />
      </header>

      <div className="flex-1 overflow-y-auto px-7 py-6 max-w-3xl">

        {fetchError && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 mb-5">
            {fetchError}
          </div>
        )}

        {runs.length === 0 && !fetchError && (
          <EmptyState icon={ListChecks} title={t("noRunsYet")} hint={t("noRunsHint")} />
        )}

        {discoveryRuns.length > 0 && (
          <div className="space-y-2 mb-6">
            <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--ink-muted)" }}>
              {t("discoverySection")}
            </h2>
            {discoveryRuns.map((run) => (
              <RunRow key={run.id} run={run} t={t} />
            ))}
          </div>
        )}

        {reportRuns.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--ink-muted)" }}>
              {t("reportsSection")}
            </h2>
            {reportRuns.map((run) => (
              <RunRow key={run.id} run={run} t={t} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
