import Link from "next/link";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { StartRunButton } from "./StartRunButton";
import { fmtTs } from "@/lib/utils";

export const dynamic = "force-dynamic";

const RUN_TYPE_LABELS: Record<string, string> = {
  job_discovery: "Discovery Run",
  job_report: "Job Intelligence Report",
  fit_report: "Fit Analysis",
};

function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABELS[runType] ?? runType.replace(/_/g, " ");
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "In Progress",
  succeeded: "Completed",
  failed: "Failed",
  needs_review: "Needs Review",
  cancelled: "Cancelled",
};

function humanStatus(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

function statusDotColor(status: string): string {
  if (status === "succeeded") return "oklch(52% 0.18 155)";
  if (status === "running") return "oklch(52% 0.18 260)";
  if (status === "failed") return "oklch(52% 0.18 25)";
  if (status === "needs_review") return "oklch(52% 0.18 80)";
  return "oklch(70% 0.01 275)";
}

function statusBadgeStyle(status: string): { bg: string; fg: string } {
  if (status === "succeeded") return { bg: "var(--match-strong-bg)", fg: "var(--match-strong-fg)" };
  if (status === "running") return { bg: "var(--match-good-bg)", fg: "var(--match-good-fg)" };
  if (status === "failed") return { bg: "oklch(95% 0.02 25)", fg: "oklch(45% 0.15 25)" };
  if (status === "needs_review") return { bg: "oklch(95% 0.03 80)", fg: "oklch(45% 0.12 80)" };
  return { bg: "var(--match-partial-bg)", fg: "var(--match-partial-fg)" };
}

function RunRow({ run }: { run: RunRead }) {
  const badge = statusBadgeStyle(run.status);
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex items-center justify-between gap-4 bg-white rounded-[10px] p-4 transition-shadow hover:shadow-md"
      style={{ border: "1px solid var(--border)", boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)" }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: statusDotColor(run.status) }}
        />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate" style={{ color: "oklch(22% 0.015 275)" }}>
            {runTypeLabel(run.run_type)}
          </p>
          <p className="text-xs mt-0.5" style={{ color: "oklch(60% 0.01 275)" }}>{fmtTs(run.created_at)}</p>
        </div>
      </div>
      <span
        className="text-xs font-medium px-2.5 py-1 rounded-full shrink-0"
        style={{ background: badge.bg, color: badge.fg }}
      >
        {humanStatus(run.status)}
      </span>
    </Link>
  );
}

export default async function RunsPage() {
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
          Reports & Runs
        </span>
        <span className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          {runs.length} run{runs.length !== 1 ? "s" : ""}
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
          <div className="rounded-xl border border-dashed py-16 text-center" style={{ borderColor: "var(--border)" }}>
            <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>No runs yet</p>
            <p className="text-xs mt-1" style={{ color: "oklch(60% 0.01 275)" }}>
              Start a Discovery Run from Searches to find matching roles.
            </p>
          </div>
        )}

        {discoveryRuns.length > 0 && (
          <div className="space-y-2 mb-6">
            <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "oklch(60% 0.01 275)" }}>
              Discovery
            </h2>
            {discoveryRuns.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}

        {reportRuns.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "oklch(60% 0.01 275)" }}>
              Reports
            </h2>
            {reportRuns.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
