"use client";

import { useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";

interface FitReportPanelProps {
  onRunCreated: (runId: string) => void;
}

export function FitReportPanel({ onRunCreated }: FitReportPanelProps) {
  const getToken = useApiToken();
  const [jobId, setJobId] = useState("");
  const [jobReportId, setJobReportId] = useState("");
  const [forceRefresh, setForceRefresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const token = await getToken();
      const run = await createRun({
        run_type: "fit_report",
        input_snapshot: {
          job_id: jobId.trim(),
          job_report_id: jobReportId.trim() || undefined,
          force_refresh: forceRefresh,
        },
      }, token);
      onRunCreated(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start fit report run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div>
        <h2 className="text-sm font-semibold text-[var(--ink-primary)]">Candidate Fit Report</h2>
        <p className="text-xs text-[var(--ink-muted)] mt-0.5">
          Evaluate how well your saved profile matches a job.
          <a href="/profile" className="ml-1 underline text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">
            Edit profile →
          </a>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs font-medium text-[var(--ink-secondary)]">
            Job ID <span className="text-rose-500">*</span>
          </label>
          <input
            required
            className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
            placeholder="job_abc123"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-[var(--ink-secondary)]">Job Report ID</label>
          <input
            className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
            placeholder="use latest active"
            value={jobReportId}
            onChange={(e) => setJobReportId(e.target.value)}
          />
        </div>
      </div>

      <label className="flex items-center gap-1.5 text-xs text-[var(--ink-secondary)] cursor-pointer">
        <input
          type="checkbox"
          checked={forceRefresh}
          onChange={(e) => setForceRefresh(e.target.checked)}
          className="rounded"
        />
        Force refresh
      </label>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      <Button
        type="submit"
        disabled={!jobId.trim()}
        loading={loading}
        size="sm"
        className="w-full"
      >
        {!loading && <Play size={13} className="mr-1.5" />}
        Generate Fit Report
      </Button>
    </form>
  );
}
