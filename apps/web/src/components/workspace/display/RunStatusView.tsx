"use client";

import { useState } from "react";
import { cancelRun } from "@/api/client";
import type { RunRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { StopCircle } from "lucide-react";
import { RunStatusStepper, type RunStatus } from "@/components/RunStatusStepper";

interface RunStatusViewProps {
  run: RunRead;
  onCancelled: (updated: RunRead) => void;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "In progress",
  succeeded: "Completed",
  failed: "Failed",
  needs_review: "Needs review",
  cancelled: "Cancelled",
};

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
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-[var(--ink-primary)]">Status</span>
        <RunStatusStepper
          status={run.status as RunStatus}
          labels={{
            queued: STATUS_LABELS.queued,
            running: STATUS_LABELS.running,
            done: STATUS_LABELS[run.status] ?? STATUS_LABELS.cancelled,
          }}
        />
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
              <dt className="w-32 shrink-0 text-[var(--ink-muted)]">{label}</dt>
              <dd className="text-[var(--ink-secondary)] font-mono break-all">{value}</dd>
            </div>
          ) : null,
        )}
      </dl>

      {/* Cancel */}
      {CANCELLABLE.has(run.status) && (
        <div className="pt-2 border-t border-[var(--border)]">
          {cancelError && (
            <p className="text-xs text-rose-600 mb-2">{cancelError}</p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleCancel}
            loading={cancelling}
            className="text-rose-600 border-rose-300 hover:bg-rose-50"
          >
            {!cancelling && <StopCircle size={13} className="mr-1.5" />}
            Request cancellation
          </Button>
          <p className="text-xs text-[var(--ink-muted)] mt-1">
            Marks the run as cancelled. In-flight agent work may still complete.
          </p>
        </div>
      )}
    </div>
  );
}
