"use client";

import { useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Loader2, Play } from "lucide-react";

interface JobReportPanelProps {
  onRunCreated: (runId: string) => void;
}

export function JobReportPanel({ onRunCreated }: JobReportPanelProps) {
  const getToken = useApiToken();
  const [jobId, setJobId] = useState("");
  const [useResearch, setUseResearch] = useState(false);
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
        run_type: "job_report",
        input_snapshot: {
          job_id: jobId.trim(),
          use_research: useResearch,
          force_refresh: forceRefresh,
        },
      }, token);
      onRunCreated(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start job report run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div>
        <h2 className="text-sm font-semibold text-zinc-800">Job Intelligence Report</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Generate a structured analysis of a specific job posting.
        </p>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-zinc-700">
          Job ID <span className="text-rose-500">*</span>
        </label>
        <input
          required
          className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
          placeholder="job_abc123"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
        />
        <p className="text-xs text-zinc-400">
          Job ID from a completed discovery run.
        </p>
      </div>

      <div className="flex gap-4">
        <label className="flex items-center gap-1.5 text-xs text-zinc-600 cursor-pointer">
          <input
            type="checkbox"
            checked={useResearch}
            onChange={(e) => setUseResearch(e.target.checked)}
            className="rounded"
          />
          Include research bundle
        </label>
        <label className="flex items-center gap-1.5 text-xs text-zinc-600 cursor-pointer">
          <input
            type="checkbox"
            checked={forceRefresh}
            onChange={(e) => setForceRefresh(e.target.checked)}
            className="rounded"
          />
          Force refresh
        </label>
      </div>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      <Button
        type="submit"
        disabled={loading || !jobId.trim()}
        size="sm"
        className="w-full"
      >
        {loading ? (
          <Loader2 size={13} className="animate-spin mr-1.5" />
        ) : (
          <Play size={13} className="mr-1.5" />
        )}
        Generate Job Report
      </Button>
    </form>
  );
}
