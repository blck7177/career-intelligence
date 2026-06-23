"use client";

import { useState } from "react";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Loader2, Play } from "lucide-react";

interface FitReportPanelProps {
  workspaceId: string;
  onRunCreated: (runId: string) => void;
}

function csvToList(val: string): string[] {
  return val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function FitReportPanel({ workspaceId, onRunCreated }: FitReportPanelProps) {
  const [jobId, setJobId] = useState("");
  const [jobReportId, setJobReportId] = useState("");
  const [forceRefresh, setForceRefresh] = useState(false);

  // Profile snapshot fields
  const [yearsExp, setYearsExp] = useState("");
  const [background, setBackground] = useState("");
  const [domainExp, setDomainExp] = useState("");
  const [techSkills, setTechSkills] = useState("");
  const [methods, setMethods] = useState("");
  const [finDomains, setFinDomains] = useState("");
  const [tools, setTools] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!jobId.trim()) return;

    setLoading(true);
    setError(null);

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

    try {
      const run = await createRun({
        run_type: "fit_report",
        workspace_id: workspaceId,
        input_snapshot: {
          job_id: jobId.trim(),
          job_report_id: jobReportId.trim() || undefined,
          profile_snapshot: profileSnapshot,
          force_refresh: forceRefresh,
        },
      });
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
        <h2 className="text-sm font-semibold text-zinc-800">Candidate Fit Report</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Evaluate how well your profile matches a job.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
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
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-700">Job Report ID</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="use latest active"
            value={jobReportId}
            onChange={(e) => setJobReportId(e.target.value)}
          />
        </div>
      </div>

      <div className="border-t border-zinc-100 pt-3">
        <p className="text-xs font-medium text-zinc-700 mb-2.5">Candidate Profile</p>

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
          <div key={label} className="space-y-1 mt-2">
            <label className="text-xs text-zinc-500">{label}</label>
            <input
              className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
              placeholder={ph}
              value={val}
              onChange={(e) => set(e.target.value)}
            />
          </div>
        ))}
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
        Generate Fit Report
      </Button>
    </form>
  );
}
