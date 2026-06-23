"use client";

import { useState } from "react";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Loader2, Play, ChevronDown, ChevronUp } from "lucide-react";

interface DiscoveryPanelProps {
  workspaceId: string;
  onRunCreated: (runId: string) => void;
}

type SearchMode = "direct" | "exploratory";
type SearchDepth = "quick" | "standard" | "deep";
type WorkArrangement = "hybrid" | "remote" | "onsite" | "any";

function csvToList(val: string): string[] {
  return val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function DiscoveryPanel({ workspaceId, onRunCreated }: DiscoveryPanelProps) {
  // Core required fields
  const [rawUserRequest, setRawUserRequest] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("exploratory");
  const [searchDepth, setSearchDepth] = useState<SearchDepth>("standard");

  // Hard constraints
  const [constraintsOpen, setConstraintsOpen] = useState(false);
  const [location, setLocation] = useState("");
  const [seniority, setSeniority] = useState("");
  const [excludeRoleTypes, setExcludeRoleTypes] = useState("");
  const [mustIncludeKeywords, setMustIncludeKeywords] = useState("");
  const [workArrangement, setWorkArrangement] = useState<WorkArrangement | "">("");
  const [visaNote, setVisaNote] = useState("");
  const [compensationRange, setCompensationRange] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = rawUserRequest.trim().length >= 5;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setLoading(true);
    setError(null);

    try {
      const run = await createRun({
        run_type: "job_discovery",
        workspace_id: workspaceId,
        input_snapshot: {
          raw_user_request: rawUserRequest.trim(),
          search_mode: searchMode,
          search_depth: searchDepth,
          hard_constraints: {
            location: location.trim() || undefined,
            seniority: csvToList(seniority),
            exclude_role_types: csvToList(excludeRoleTypes),
            must_include_keywords: csvToList(mustIncludeKeywords),
            work_arrangement: workArrangement || undefined,
            visa_note: visaNote.trim() || undefined,
            compensation_range: compensationRange.trim() || undefined,
          },
          profile_id: undefined,
        },
      });
      onRunCreated(run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start discovery run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div>
        <h2 className="text-sm font-semibold text-zinc-800">Discovery</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Find matching jobs using the career search agent.
        </p>
      </div>

      {/* Search request */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-zinc-700">
          Search Request <span className="text-rose-500">*</span>
        </label>
        <textarea
          rows={4}
          required
          minLength={5}
          placeholder="e.g. Looking for market risk roles at mid-size banks in NYC, ideally VP or SVP level, quantitative background preferred..."
          value={rawUserRequest}
          onChange={(e) => setRawUserRequest(e.target.value)}
          className="w-full rounded border border-zinc-300 bg-white px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400 resize-none"
        />
        <p className="text-xs text-zinc-400">
          {rawUserRequest.trim().length < 5
            ? `${5 - rawUserRequest.trim().length} more characters required`
            : `${rawUserRequest.trim().length} chars`}
        </p>
      </div>

      {/* Search mode */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-zinc-700">Search Mode</label>
        <div className="flex gap-2">
          {(["direct", "exploratory"] as SearchMode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setSearchMode(mode)}
              className={[
                "flex-1 py-1.5 text-xs rounded border transition-colors",
                searchMode === mode
                  ? "border-zinc-800 bg-zinc-800 text-white"
                  : "border-zinc-300 text-zinc-600 hover:border-zinc-400",
              ].join(" ")}
            >
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
          <button
            type="button"
            disabled
            title="Requires a saved profile — coming later"
            className="flex-1 py-1.5 text-xs rounded border border-zinc-200 text-zinc-300 cursor-not-allowed"
          >
            Profile-guided
          </button>
        </div>
        <p className="text-xs text-zinc-400">
          {searchMode === "direct"
            ? "Minimal expansion — targets your exact role description."
            : "Explores adjacent roles — broader search around your direction."}
        </p>
      </div>

      {/* Search depth */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-zinc-700">Search Depth</label>
        <div className="flex gap-2">
          {(
            [
              { val: "quick", hint: "~20 candidates" },
              { val: "standard", hint: "~50 candidates" },
              { val: "deep", hint: "~100 candidates" },
            ] as { val: SearchDepth; hint: string }[]
          ).map(({ val, hint }) => (
            <button
              key={val}
              type="button"
              onClick={() => setSearchDepth(val)}
              className={[
                "flex-1 py-1.5 text-xs rounded border transition-colors",
                searchDepth === val
                  ? "border-zinc-800 bg-zinc-800 text-white"
                  : "border-zinc-300 text-zinc-600 hover:border-zinc-400",
              ].join(" ")}
            >
              <span className="block">{val.charAt(0).toUpperCase() + val.slice(1)}</span>
              <span className="block text-[10px] opacity-70">{hint}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Hard constraints (collapsible) */}
      <div className="border border-zinc-200 rounded-lg">
        <button
          type="button"
          onClick={() => setConstraintsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-zinc-700 hover:bg-zinc-50 rounded-lg transition-colors"
        >
          <span>Hard Constraints</span>
          {constraintsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {constraintsOpen && (
          <div className="px-3 pb-3 space-y-2.5 border-t border-zinc-100">
            <div className="grid grid-cols-2 gap-2 pt-2.5">
              <div className="space-y-1">
                <label className="text-xs text-zinc-500">Location</label>
                <input
                  className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                  placeholder="NYC, remote US..."
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-zinc-500">Work Arrangement</label>
                <select
                  value={workArrangement}
                  onChange={(e) => setWorkArrangement(e.target.value as WorkArrangement | "")}
                  className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                >
                  <option value="">No preference</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="remote">Remote</option>
                  <option value="onsite">Onsite</option>
                  <option value="any">Any</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Seniority levels (comma-sep)</label>
              <input
                className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                placeholder="analyst, associate, avp, vp"
                value={seniority}
                onChange={(e) => setSeniority(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Must include keywords (comma-sep)</label>
              <input
                className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                placeholder="market risk, quantitative"
                value={mustIncludeKeywords}
                onChange={(e) => setMustIncludeKeywords(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Exclude role types (comma-sep)</label>
              <input
                className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                placeholder="model_validation, pure_audit"
                value={excludeRoleTypes}
                onChange={(e) => setExcludeRoleTypes(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-xs text-zinc-500">Compensation range</label>
                <input
                  className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                  placeholder="$120k–$160k"
                  value={compensationRange}
                  onChange={(e) => setCompensationRange(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-zinc-500">Visa note</label>
                <input
                  className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-zinc-400"
                  placeholder="H1B transfer only"
                  value={visaNote}
                  onChange={(e) => setVisaNote(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      <Button
        type="submit"
        disabled={loading || !canSubmit}
        size="sm"
        className="w-full"
      >
        {loading ? (
          <Loader2 size={13} className="animate-spin mr-1.5" />
        ) : (
          <Play size={13} className="mr-1.5" />
        )}
        Start Discovery Run
      </Button>
    </form>
  );
}
