"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { statusBg, fmtTs } from "@/lib/utils";
import { CheckCircle2, XCircle, Circle, AlertCircle, RefreshCw } from "lucide-react";

interface RunsPanelProps {
  activeRunId?: string;
  onSelectRun: (runId: string) => void;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={12} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={12} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={12} className="text-blue-500 animate-pulse shrink-0" />;
  return <Circle size={12} className="text-zinc-400 shrink-0" />;
}

export function RunsPanel({ activeRunId, onSelectRun }: RunsPanelProps) {
  const { getToken } = useAuth();
  const [runs, setRuns] = useState<RunRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchRuns() {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const list = await listRuns(token);
      setRuns(list.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-800">Runs</h2>
          <p className="text-xs text-zinc-500 mt-0.5">Select a run to inspect.</p>
        </div>
        <button
          onClick={fetchRuns}
          disabled={loading}
          className="p-1.5 rounded text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      {!loading && runs.length === 0 && !error && (
        <p className="text-xs text-zinc-400 py-4 text-center">
          No runs yet. Use Discovery, Job Report, or Fit Report to create one.
        </p>
      )}

      <ul className="space-y-1">
        {runs.map((run) => (
          <li key={run.id}>
            <button
              onClick={() => onSelectRun(run.id)}
              className={[
                "w-full flex items-start gap-2 px-3 py-2.5 rounded-lg border text-left transition-colors",
                activeRunId === run.id
                  ? "border-zinc-800 bg-zinc-50"
                  : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
              ].join(" ")}
            >
              <StatusIcon status={run.status} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-mono text-zinc-700 truncate">{run.id}</p>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {run.run_type.replace(/_/g, " ")} · {fmtTs(run.created_at)}
                </p>
              </div>
              <Badge className={statusBg(run.status) + " text-[10px] shrink-0"}>
                {run.status.replace("_", " ")}
              </Badge>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
