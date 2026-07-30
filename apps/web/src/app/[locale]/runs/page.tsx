import { getTranslations } from "next-intl/server";
import { ListChecks } from "lucide-react";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { fmtTs } from "@/lib/utils";
import { RunRow } from "@/components/RunRow";
import { EmptyState } from "@/components/EmptyState";
import { PageContainer } from "@/components/ui/page-container";
import { PageHeader } from "@/components/ui/page-header";
import { ZoneHead } from "@/components/ui/zone-head";
import { Banner } from "@/components/ui/banner";

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

  const renderRun = (run: RunRead) => (
    <RunRow
      key={run.id}
      status={run.status}
      href={`/runs/${run.id}`}
      typeLabel={t(RUN_TYPE_KEYS[run.run_type] ?? "runDiscovery")}
      statusLabel={t(STATUS_KEYS[run.status] ?? "statusQueued")}
      timeLabel={fmtTs(run.created_at)}
    />
  );

  return (
    <>
      <div className="flex-1 overflow-y-auto">
        <PageContainer variant="narrow">

        {/* Page identity — no page-owned header bar; the shared top bar
            already carries "New Run" for this section. gutter="none" so the
            title shares PageContainer's 28px gutter with the rows below. */}
        <PageHeader
          title={t("title")}
          meta={t("runCount", { count: runs.length })}
          gutter="none"
          className="mb-[var(--space-stack-md)]"
        />

        {fetchError && (
          <Banner variant="danger" className="mb-[var(--space-stack-md)]">
            {fetchError}
          </Banner>
        )}

        {runs.length === 0 && !fetchError && (
          <EmptyState icon={ListChecks} title={t("noRunsYet")} hint={t("noRunsHint")} />
        )}

        {discoveryRuns.length > 0 && (
          <div className="mb-[var(--space-stack-lg)]">
            <ZoneHead title={t("discoverySection")} sub={t("runCount", { count: discoveryRuns.length })} />
            <div className="space-y-[var(--space-stack-xs)]">
              {discoveryRuns.map(renderRun)}
            </div>
          </div>
        )}

        {reportRuns.length > 0 && (
          <div>
            <ZoneHead title={t("reportsSection")} sub={t("runCount", { count: reportRuns.length })} />
            <div className="space-y-[var(--space-stack-xs)]">
              {reportRuns.map(renderRun)}
            </div>
          </div>
        )}
        </PageContainer>
      </div>
    </>
  );
}
