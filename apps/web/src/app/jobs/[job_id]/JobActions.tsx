"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Loader2, FileText, UserCheck, ChevronDown, ChevronUp, Play } from "lucide-react";

function csvToList(val: string): string[] {
  return val.split(",").map((s) => s.trim()).filter(Boolean);
}

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
  const { getToken } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobReportId, setJobReportId] = useState("");
  const [yearsExp, setYearsExp] = useState("");
  const [background, setBackground] = useState("");
  const [domainExp, setDomainExp] = useState("");
  const [techSkills, setTechSkills] = useState("");
  const [methods, setMethods] = useState("");
  const [finDomains, setFinDomains] = useState("");
  const [tools, setTools] = useState("");

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
          profile_snapshot: {
            years_experience: yearsExp ? Number(yearsExp) : undefined,
            current_background: background.trim() || undefined,
            domain_experience: csvToList(domainExp),
            technical_skills: csvToList(techSkills),
            analytical_methods: csvToList(methods),
            finance_domains: csvToList(finDomains),
            tools: csvToList(tools),
            representative_projects: [],
          },
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
        <p className="text-xs font-medium text-zinc-700">Candidate Profile</p>
        <button type="button" onClick={onCancel} className="text-xs text-zinc-400 hover:text-zinc-600">
          Cancel
        </button>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Job Report ID (optional — uses latest if omitted)</label>
        <input
          className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
          placeholder="jr_abc123"
          value={jobReportId}
          onChange={(e) => setJobReportId(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Years of experience</label>
          <input type="number" min={0}
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="5" value={yearsExp} onChange={(e) => setYearsExp(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Current background</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder="VP Risk at bulge bracket" value={background} onChange={(e) => setBackground(e.target.value)} />
        </div>
      </div>

      {[
        { label: "Domain experience (comma-sep)", val: domainExp, set: setDomainExp, ph: "market risk, credit risk" },
        { label: "Technical skills (comma-sep)", val: techSkills, set: setTechSkills, ph: "Python, SQL" },
        { label: "Analytical methods (comma-sep)", val: methods, set: setMethods, ph: "VaR, stress testing" },
        { label: "Finance domains (comma-sep)", val: finDomains, set: setFinDomains, ph: "derivatives, fixed income" },
        { label: "Tools (comma-sep)", val: tools, set: setTools, ph: "Bloomberg, Excel" },
      ].map(({ label, val, set, ph }) => (
        <div key={label} className="space-y-1">
          <label className="text-xs text-zinc-500">{label}</label>
          <input
            className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
            placeholder={ph} value={val} onChange={(e) => set(e.target.value)} />
        </div>
      ))}

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
  const { getToken } = useAuth();
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
