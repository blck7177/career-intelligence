"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { Button } from "@/components/ui/button";
import { createRun, type RunCreate } from "@/api/client";
import { Plus, Loader2, X, ChevronDown } from "lucide-react";

type FormMode = "none" | "job_report" | "fit_report" | "discovery";

// ---------------------------------------------------------------------------
// Sub-forms
// ---------------------------------------------------------------------------

function JobReportForm({
  onSubmit,
  onCancel,
  loading,
}: {
  onSubmit: (body: RunCreate) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [jobId, setJobId] = useState("");
  const [useResearch, setUseResearch] = useState(false);
  const [researchArtifactId, setResearchArtifactId] = useState("");
  const [forceRefresh, setForceRefresh] = useState(false);

  const researchBlocked = useResearch && !researchArtifactId.trim();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim() || researchBlocked) return;
    onSubmit({
      run_type: "job_report",
      input_snapshot: {
        job_id: jobId.trim(),
        use_research: useResearch,
        research_artifact_id: useResearch ? researchArtifactId.trim() : undefined,
        force_refresh: forceRefresh,
      },
    });
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="font-medium text-zinc-700">Generate Job Intelligence Report</p>
        <button type="button" onClick={onCancel} className="text-zinc-400 hover:text-zinc-600">
          <X size={14} />
        </button>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Job ID *</label>
        <input
          className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
          placeholder="job_abc123"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          required
        />
      </div>

      <div className="flex gap-4">
        <label className="flex items-center gap-1.5 text-xs text-zinc-600 cursor-pointer">
          <input
            type="checkbox"
            checked={useResearch}
            onChange={(e) => setUseResearch(e.target.checked)}
            className="rounded"
          />
          Use research
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

      {useResearch && (
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Research Artifact ID *</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="art_abc123"
            value={researchArtifactId}
            onChange={(e) => setResearchArtifactId(e.target.value)}
          />
          <p className="text-xs text-zinc-400">
            Find artifact IDs in the Events log of a completed research run.
          </p>
          {researchBlocked && (
            <p className="text-xs text-rose-600">
              Research artifact ID is required when &ldquo;Use research&rdquo; is checked.
            </p>
          )}
        </div>
      )}

      <Button type="submit" disabled={loading || !jobId.trim() || researchBlocked} size="sm" className="w-full">
        {loading ? <Loader2 size={13} className="animate-spin mr-1.5" /> : <Plus size={13} className="mr-1.5" />}
        Start Job Report Run
      </Button>
    </form>
  );
}

function FitReportForm({
  onSubmit,
  onCancel,
  loading,
}: {
  onSubmit: (body: RunCreate) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [jobId, setJobId] = useState("");
  const [jobReportId, setJobReportId] = useState("");
  const [forceRefresh, setForceRefresh] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim()) return;
    onSubmit({
      run_type: "fit_report",
      input_snapshot: {
        job_id: jobId.trim(),
        job_report_id: jobReportId.trim() || undefined,
        force_refresh: forceRefresh,
      },
    });
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <p className="font-medium text-zinc-700">Generate Candidate Fit Report</p>
        <button type="button" onClick={onCancel} className="text-zinc-400 hover:text-zinc-600">
          <X size={14} />
        </button>
      </div>

      <p className="text-xs text-zinc-500">
        Uses your saved candidate profile.{" "}
        <a href="/profile" className="underline text-zinc-400 hover:text-zinc-600">Edit profile →</a>
      </p>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Job ID *</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="job_abc123"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Job Report ID (optional)</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="use latest active"
            value={jobReportId}
            onChange={(e) => setJobReportId(e.target.value)}
          />
        </div>
      </div>

      <label className="flex items-center gap-1.5 text-xs text-zinc-600 cursor-pointer">
        <input
          type="checkbox"
          checked={forceRefresh}
          onChange={(e) => setForceRefresh(e.target.checked)}
          className="rounded"
        />
        Force refresh
      </label>

      <Button type="submit" disabled={loading || !jobId.trim()} size="sm" className="w-full">
        {loading ? <Loader2 size={13} className="animate-spin mr-1.5" /> : <Plus size={13} className="mr-1.5" />}
        Start Fit Report Run
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function StartRunButton() {
  const router = useRouter();
  const getToken = useApiToken();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<FormMode>("none");
  const [menuOpen, setMenuOpen] = useState(false);

  async function startRun(body: RunCreate) {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const run = await createRun(body, token);
      setFormMode("none");
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setLoading(false);
    }
  }

  function openForm(mode: FormMode) {
    setFormMode(mode);
    setMenuOpen(false);
    setError(null);
  }

  return (
    <div className="relative">
      {/* Button group */}
      <div className="flex items-center gap-1">
        <Button
          onClick={() => router.push("/workspace")}
          disabled={loading}
          size="sm"
        >
          <Plus size={14} className="mr-1.5" />
          New Run
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setMenuOpen((o) => !o)}
          disabled={loading}
          className="px-2"
          aria-label="Run type menu"
        >
          <ChevronDown size={14} />
        </Button>
      </div>

      {/* Dropdown menu */}
      {menuOpen && (
        <div className="absolute right-0 top-full mt-1 w-52 rounded-lg border border-zinc-200 bg-white shadow-md z-10">
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-zinc-50 rounded-t-lg"
            onClick={() => { router.push("/workspace"); setMenuOpen(false); }}
          >
            Discovery Run
          </button>
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-zinc-50"
            onClick={() => openForm("job_report")}
          >
            Job Intelligence Report
          </button>
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-zinc-50 rounded-b-lg"
            onClick={() => openForm("fit_report")}
          >
            Candidate Fit Report
          </button>
        </div>
      )}

      {/* Inline forms */}
      {formMode === "job_report" && (
        <JobReportForm
          loading={loading}
          onCancel={() => { setFormMode("none"); setError(null); }}
          onSubmit={(body) => startRun(body)}
        />
      )}
      {formMode === "fit_report" && (
        <FitReportForm
          loading={loading}
          onCancel={() => { setFormMode("none"); setError(null); }}
          onSubmit={(body) => startRun(body)}
        />
      )}

      {error && <p className="text-xs text-rose-600 mt-1">{error}</p>}
    </div>
  );
}
