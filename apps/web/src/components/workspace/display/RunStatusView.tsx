"use client";

import { useState } from "react";
import { cancelRun } from "@/api/client";
import type { RunRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { statusBg, fmtTs } from "@/lib/utils";
import {
  CheckCircle2,
  XCircle,
  Circle,
  AlertCircle,
  StopCircle,
  Loader2,
} from "lucide-react";

interface RunStatusViewProps {
  run: RunRead;
  onCancelled: (updated: RunRead) => void;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={16} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={16} className="text-rose-500" />;
  if (status === "needs_review") return <AlertCircle size={16} className="text-amber-500" />;
  if (status === "running") return <Circle size={16} className="text-blue-500 animate-pulse" />;
  if (status === "cancelled") return <StopCircle size={16} className="text-zinc-400" />;
  return <Circle size={16} className="text-zinc-300" />;
}

const CANCELLABLE = new Set(["queued", "running"]);

export function RunStatusView({ run, onCancelled }: RunStatusViewProps) {
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  async function handleCancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      const updated = await cancelRun(run.id);
      onCancelled(updated);
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : "Failed to cancel run");
    } finally {
      setCancelling(false);
    }
  }

  const fields: { label: string; value: string | undefined | null }[] = [
    { label: "Run ID", value: run.id },
    { label: "Type", value: run.run_type.replace(/_/g, " ") },
    { label: "Workspace", value: run.workspace_id },
    { label: "Created", value: fmtTs(run.created_at) },
    { label: "Updated", value: fmtTs(run.updated_at) },
    { label: "Correlation ID", value: run.correlation_id },
    { label: "Schema Version", value: run.schema_version },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <StatusIcon status={run.status} />
          <span className="text-sm font-semibold text-zinc-800">
            {run.status.replace(/_/g, " ")}
          </span>
        </div>
        <Badge className={statusBg(run.status) + " text-xs"}>{run.status.replace("_", " ")}</Badge>
      </div>

      {/* Error banner */}
      {run.error_code && (
        <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <p className="font-semibold">{run.error_code}</p>
          {run.error_message && <p className="mt-0.5">{run.error_message}</p>}
        </div>
      )}

      {/* Fields */}
      <dl className="space-y-1.5">
        {fields.map(({ label, value }) =>
          value ? (
            <div key={label} className="flex gap-2 text-xs">
              <dt className="w-32 shrink-0 text-zinc-400">{label}</dt>
              <dd className="text-zinc-700 font-mono break-all">{value}</dd>
            </div>
          ) : null,
        )}
      </dl>

      {/* Cancel */}
      {CANCELLABLE.has(run.status) && (
        <div className="pt-2 border-t border-zinc-100">
          {cancelError && (
            <p className="text-xs text-rose-600 mb-2">{cancelError}</p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleCancel}
            disabled={cancelling}
            className="text-rose-600 border-rose-300 hover:bg-rose-50"
          >
            {cancelling ? (
              <Loader2 size={13} className="animate-spin mr-1.5" />
            ) : (
              <StopCircle size={13} className="mr-1.5" />
            )}
            Request cancellation
          </Button>
          <p className="text-xs text-zinc-400 mt-1">
            Marks the run as cancelled. In-flight agent work may still complete.
          </p>
        </div>
      )}
    </div>
  );
}
