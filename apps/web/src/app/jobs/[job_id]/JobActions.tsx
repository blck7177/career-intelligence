"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Loader2, FileText, UserCheck, ChevronDown, ChevronUp, Play } from "lucide-react";

// ---------------------------------------------------------------------------
// Fit Report inline form
// ---------------------------------------------------------------------------

function FitReportForm({
  jobId,
  onCancel,
}: {
  jobId: string;
  onCancel: () => void;
}) {
  const router = useRouter();
  const getToken = useApiToken();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobReportId, setJobReportId] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const run = await createRun({
        run_type: "fit_report",
        input_snapshot: {
          job_id: jobId,
          job_report_id: jobReportId.trim() || undefined,
          force_refresh: false,
        },
      }, token);
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start fit report run");
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-700">Candidate Fit Report</p>
        <button type="button" onClick={onCancel} className="text-xs text-zinc-400 hover:text-zinc-600">
          Cancel
        </button>
      </div>

      <p className="text-xs text-zinc-500">
        Uses your saved candidate profile.{" "}
        <a href="/profile" className="underline text-zinc-400 hover:text-zinc-600">Edit profile →</a>
      </p>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Job Report ID (optional — uses latest if omitted)</label>
        <input
          className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
          placeholder="jr_abc123"
          value={jobReportId}
          onChange={(e) => setJobReportId(e.target.value)}
        />
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}

      <Button type="submit" disabled={loading} size="sm" className="w-full">
        {loading ? <Loader2 size={13} className="animate-spin mr-1.5" /> : <Play size={13} className="mr-1.5" />}
        Generate Fit Report
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main JobActions component
// ---------------------------------------------------------------------------

interface JobActionsProps {
  jobId: string;
  hasExistingReport: boolean;
}

export function JobActions({ jobId, hasExistingReport }: JobActionsProps) {
  const router = useRouter();
  const getToken = useApiToken();
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [fitOpen, setFitOpen] = useState(false);

  async function handleGenerateReport() {
    setReportLoading(true);
    setReportError(null);
    try {
      const token = await getToken();
      const run = await createRun({
        run_type: "job_report",
        input_snapshot: {
          job_id: jobId,
          use_research: false,
          force_refresh: false,
        },
      }, token);
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Failed to start job report run");
      setReportLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Actions</p>

      {/* Job Intelligence Report */}
      <div className="space-y-1">
        <Button
          onClick={handleGenerateReport}
          disabled={reportLoading}
          size="sm"
          variant={hasExistingReport ? "outline" : "default"}
          className="w-full justify-start"
        >
          {reportLoading ? (
            <Loader2 size={13} className="animate-spin mr-2" />
          ) : (
            <FileText size={13} className="mr-2" />
          )}
          {hasExistingReport ? "Refresh Job Report" : "Generate Job Report"}
        </Button>
        {reportError && <p className="text-xs text-rose-600">{reportError}</p>}
      </div>

      {/* Candidate Fit Report */}
      <div className="space-y-1">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full justify-start"
          onClick={() => setFitOpen((o) => !o)}
        >
          <UserCheck size={13} className="mr-2" />
          Analyze Fit
          {fitOpen ? <ChevronUp size={13} className="ml-auto" /> : <ChevronDown size={13} className="ml-auto" />}
        </Button>
        {fitOpen && (
          <FitReportForm jobId={jobId} onCancel={() => setFitOpen(false)} />
        )}
      </div>
    </div>
  );
}
