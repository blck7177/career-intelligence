"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { createRun } from "@/api/client";
import { Plus, Loader2, X, ChevronDown } from "lucide-react";

const WORKSPACE_ID = process.env.NEXT_PUBLIC_WORKSPACE_ID ?? "ws_default";

type FormMode = "none" | "job_report" | "fit_report";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function csvToList(val: string): string[] {
  return val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// Sub-forms
// ---------------------------------------------------------------------------

function JobReportForm({
  onSubmit,
  onCancel,
  loading,
}: {
  onSubmit: (snapshot: Record<string, unknown>) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [jobId, setJobId] = useState("");
  const [useResearch, setUseResearch] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim()) return;
    onSubmit({ job_id: jobId.trim(), use_research: useResearch, force_refresh: forceRefresh });
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

      <Button type="submit" disabled={loading || !jobId.trim()} size="sm" className="w-full">
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
  onSubmit: (snapshot: Record<string, unknown>) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [jobId, setJobId] = useState("");
  const [jobReportId, setJobReportId] = useState("");
  const [yearsExp, setYearsExp] = useState("");
  const [background, setBackground] = useState("");
  const [domainExp, setDomainExp] = useState("");
  const [techSkills, setTechSkills] = useState("");
  const [methods, setMethods] = useState("");
  const [finDomains, setFinDomains] = useState("");
  const [tools, setTools] = useState("");
  const [forceRefresh, setForceRefresh] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim()) return;

    const profileSnapshot: Record<string, unknown> = {
      years_experience: yearsExp ? Number(yearsExp) : undefined,
      current_background: background.trim() || undefined,
      domain_experience: csvToList(domainExp),
      technical_skills: csvToList(techSkills),
      analytical_methods: csvToList(methods),
      finance_domains: csvToList(finDomains),
      tools: csvToList(tools),
      representative_projects: [],
    };

    onSubmit({
      job_id: jobId.trim(),
      job_report_id: jobReportId.trim() || undefined,
      profile_snapshot: profileSnapshot,
      force_refresh: forceRefresh,
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

      <p className="text-xs font-medium text-zinc-600 pt-1">Candidate Profile</p>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Years of experience</label>
          <input
            type="number"
            min={0}
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="5"
            value={yearsExp}
            onChange={(e) => setYearsExp(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Current background</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="VP Risk at bulge bracket"
            value={background}
            onChange={(e) => setBackground(e.target.value)}
          />
        </div>
      </div>

      {[
        { label: "Domain experience (comma-sep)", val: domainExp, set: setDomainExp, ph: "market risk, credit risk" },
        { label: "Technical skills (comma-sep)", val: techSkills, set: setTechSkills, ph: "Python, SQL, VBA" },
        { label: "Analytical methods (comma-sep)", val: methods, set: setMethods, ph: "VaR, stress testing" },
        { label: "Finance domains (comma-sep)", val: finDomains, set: setFinDomains, ph: "derivatives, fixed income" },
        { label: "Tools (comma-sep)", val: tools, set: setTools, ph: "Bloomberg, Excel" },
      ].map(({ label, val, set, ph }) => (
        <div key={label} className="space-y-1">
          <label className="text-xs text-zinc-500">{label}</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder={ph}
            value={val}
            onChange={(e) => set(e.target.value)}
          />
        </div>
      ))}

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<FormMode>("none");
  const [menuOpen, setMenuOpen] = useState(false);

  async function startRun(runType: string, inputSnapshot: Record<string, unknown>) {
    setLoading(true);
    setError(null);
    try {
      const run = await createRun({
        run_type: runType,
        workspace_id: WORKSPACE_ID,
        input_snapshot: inputSnapshot,
      });
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
          onClick={() => startRun("job_discovery", {})}
          disabled={loading}
          size="sm"
        >
          {loading && formMode === "none" ? (
            <Loader2 size={14} className="animate-spin mr-1.5" />
          ) : (
            <Plus size={14} className="mr-1.5" />
          )}
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
            onClick={() => { startRun("job_discovery", {}); setMenuOpen(false); }}
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
          onSubmit={(snap) => startRun("job_report", snap)}
        />
      )}
      {formMode === "fit_report" && (
        <FitReportForm
          loading={loading}
          onCancel={() => { setFormMode("none"); setError(null); }}
          onSubmit={(snap) => startRun("fit_report", snap)}
        />
      )}

      {error && <p className="text-xs text-rose-600 mt-1">{error}</p>}
    </div>
  );
}
