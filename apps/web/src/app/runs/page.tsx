import Link from "next/link";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { StartRunButton } from "./StartRunButton";
import { CheckCircle2, XCircle, Circle, AlertCircle, Clock } from "lucide-react";
import { fmtTs } from "@/lib/utils";

export const dynamic = "force-dynamic";

// ---------------------------------------------------------------------------
// Label helpers
// ---------------------------------------------------------------------------

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

function statusBadgeClass(status: string): string {
  if (status === "succeeded") return "bg-emerald-100 text-emerald-700";
  if (status === "running") return "bg-blue-100 text-blue-700";
  if (status === "queued") return "bg-zinc-100 text-zinc-600";
  if (status === "needs_review") return "bg-amber-100 text-amber-700";
  if (status === "failed") return "bg-rose-100 text-rose-700";
  return "bg-zinc-100 text-zinc-500";
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={14} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={14} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={14} className="text-blue-500 animate-pulse shrink-0" />;
  if (status === "cancelled") return <Circle size={14} className="text-zinc-400 shrink-0" />;
  return <Clock size={14} className="text-zinc-400 shrink-0" />;
}

function RunRow({ run }: { run: RunRead }) {
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex items-center justify-between gap-4 border border-zinc-200 rounded-lg bg-white p-4 hover:border-zinc-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-center gap-3 min-w-0">
        <StatusIcon status={run.status} />
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-800 truncate">
            {runTypeLabel(run.run_type)}
          </p>
          <p className="text-xs text-zinc-400 mt-0.5">{fmtTs(run.created_at)}</p>
        </div>
      </div>
      <Badge className={statusBadgeClass(run.status) + " text-xs shrink-0"}>
        {humanStatus(run.status)}
      </Badge>
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
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Search Runs</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {runs.length} run{runs.length !== 1 ? "s" : ""}
          </p>
        </div>
        <StartRunButton />
      </div>

      {fetchError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {fetchError}
        </div>
      )}

      {runs.length === 0 && !fetchError && (
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center space-y-2">
          <p className="text-zinc-500 text-sm font-medium">No runs yet</p>
          <p className="text-zinc-400 text-xs">
            Start a Discovery Run from Search Setup to find matching roles.
          </p>
        </div>
      )}

      {/* Discovery runs */}
      {discoveryRuns.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            Discovery
          </h2>
          {discoveryRuns.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}

      {/* Report runs */}
      {reportRuns.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            Reports
          </h2>
          {reportRuns.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  );
}
