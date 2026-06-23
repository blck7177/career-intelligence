import Link from "next/link";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { StartRunButton } from "./StartRunButton";
import { CheckCircle2, XCircle, Circle, AlertCircle } from "lucide-react";
import { fmtTs, statusBg } from "@/lib/utils";

export const dynamic = "force-dynamic";

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={14} className="text-rose-500" />;
  if (status === "needs_review") return <AlertCircle size={14} className="text-amber-500" />;
  if (status === "running") return <Circle size={14} className="text-blue-500 animate-pulse" />;
  return <Circle size={14} className="text-zinc-400" />;
}

function RunRow({ run }: { run: RunRead }) {
  return (
    <Link
      href={`/runs/${run.id}`}
      className="flex items-center justify-between border border-zinc-200 rounded-lg p-4 hover:bg-zinc-50 transition-colors"
    >
      <div className="flex items-center gap-3">
        <StatusIcon status={run.status} />
        <div>
          <p className="text-sm font-medium font-mono">{run.id}</p>
          <p className="text-xs text-zinc-500 mt-0.5">
            {run.run_type.replace("_", " ")} · {fmtTs(run.created_at)}
          </p>
        </div>
      </div>
      <Badge className={statusBg(run.status)}>{run.status.replace("_", " ")}</Badge>
    </Link>
  );
}

export default async function RunsPage() {
  let runs: RunRead[] = [];
  let fetchError: string | null = null;

  try {
    const list = await listRuns();
    runs = list.items;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Failed to load runs";
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
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

      {runs.length === 0 && !fetchError ? (
        <p className="text-zinc-500 py-10 text-center text-sm">
          No runs yet. Click &ldquo;New Discovery Run&rdquo; to start.
        </p>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  );
}
