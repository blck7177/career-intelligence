"use client";

import { useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Play, ChevronDown, MapPinned, Heart } from "lucide-react";
import { Collapsible } from "@/components/Collapsible";
import { BAND } from "@/lib/matchBand";

const MIN_REQUEST_LENGTH = 5;

interface DiscoveryPanelProps {
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

export function DiscoveryPanel({ onRunCreated }: DiscoveryPanelProps) {
  const getToken = useApiToken();
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
  const [softPreferences, setSoftPreferences] = useState("");
  const [softPreferencesOpen, setSoftPreferencesOpen] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = rawUserRequest.trim().length >= MIN_REQUEST_LENGTH;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setLoading(true);
    setError(null);

    try {
      const token = await getToken();
      const run = await createRun({
        run_type: "job_discovery",
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
          soft_preferences: csvToList(softPreferences),
          profile_id: undefined,
        },
      }, token);
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
        <h2 className="text-sm font-semibold text-[var(--ink-primary)]">Discovery</h2>
        <p className="text-xs text-[var(--ink-muted)] mt-0.5">
          Find matching jobs using the career search agent.
        </p>
      </div>

      {/* Search request */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[var(--ink-secondary)]">
          Search Request <span className="text-rose-500">*</span>
        </label>
        <textarea
          rows={4}
          required
          minLength={MIN_REQUEST_LENGTH}
          placeholder="e.g. Looking for market risk roles at mid-size banks in NYC, ideally VP or SVP level, quantitative background preferred..."
          value={rawUserRequest}
          onChange={(e) => setRawUserRequest(e.target.value)}
          className="w-full rounded border border-[var(--border)] bg-white px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40 resize-none"
        />
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-[var(--muted)] overflow-hidden">
            <div
              className="h-full rounded-full transition-[width] duration-300"
              style={{
                width: `${Math.min(100, (rawUserRequest.trim().length / MIN_REQUEST_LENGTH) * 100)}%`,
                backgroundColor: canSubmit ? BAND.strong.ring : "var(--primary)",
              }}
            />
          </div>
          <span className="text-[11px] text-[var(--ink-muted)] whitespace-nowrap">
            {canSubmit
              ? `${rawUserRequest.trim().length} chars`
              : `${MIN_REQUEST_LENGTH - rawUserRequest.trim().length} more required`}
          </span>
        </div>
      </div>

      {/* Search mode */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[var(--ink-secondary)]">Search Mode</label>
        <div className="flex gap-2">
          {(["direct", "exploratory"] as SearchMode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setSearchMode(mode)}
              className={[
                "flex-1 py-1.5 text-xs rounded border transition-colors",
                searchMode === mode
                  ? "border-[var(--primary)] bg-[var(--primary)] text-white"
                  : "border-[var(--border)] text-[var(--ink-secondary)] hover:border-[var(--ink-faint)]",
              ].join(" ")}
            >
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
          <button
            type="button"
            disabled
            title="Requires a saved profile — coming later"
            className="flex-1 py-1.5 text-xs rounded border border-[var(--border)] text-[var(--ink-faint)] cursor-not-allowed"
          >
            Profile-guided
          </button>
        </div>
        <p className="text-xs text-[var(--ink-muted)]">
          {searchMode === "direct"
            ? "Minimal expansion — targets your exact role description."
            : "Explores adjacent roles — broader search around your direction."}
        </p>
      </div>

      {/* Search depth */}
      <div className="space-y-1">
        <label className="text-xs font-medium text-[var(--ink-secondary)]">Search Depth</label>
        <div className="flex gap-2">
          {(
            [
              { val: "quick", intensity: 1, hint: "~20 candidates" },
              { val: "standard", intensity: 2, hint: "~50 candidates" },
              { val: "deep", intensity: 3, hint: "~100 candidates" },
            ] as { val: SearchDepth; intensity: 1 | 2 | 3; hint: string }[]
          ).map(({ val, intensity, hint }) => {
            const active = searchDepth === val;
            return (
              <button
                key={val}
                type="button"
                onClick={() => setSearchDepth(val)}
                className={[
                  "flex-1 flex flex-col items-center gap-1.5 py-2 text-xs rounded-lg border transition-colors",
                  active
                    ? "border-[var(--primary)]"
                    : "border-[var(--border)] hover:border-[var(--ink-faint)]",
                ].join(" ")}
                style={active ? { background: "var(--secondary)" } : undefined}
              >
                <span className="flex items-center gap-[3px]">
                  {[1, 2, 3].map((dot) => (
                    <span
                      key={dot}
                      className="w-1.5 h-1.5 rounded-full"
                      style={{
                        background: dot <= intensity
                          ? active
                            ? "var(--primary)"
                            : "var(--ink-faint)"
                          : "var(--border)",
                      }}
                    />
                  ))}
                </span>
                <span className={active ? "font-medium" : "text-[var(--ink-secondary)]"} style={active ? { color: "var(--secondary-foreground)" } : undefined}>
                  {val.charAt(0).toUpperCase() + val.slice(1)}
                </span>
                <span className="text-[10px] text-[var(--ink-muted)]">{hint}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Hard constraints (collapsible) */}
      <div className="border border-[var(--border)] rounded-lg">
        <button
          type="button"
          onClick={() => setConstraintsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-[var(--ink-secondary)] hover:bg-[var(--muted)] rounded-lg transition-colors"
        >
          <span className="flex items-center gap-2">
            <span className="flex items-center justify-center w-5 h-5 rounded-full shrink-0 bg-[var(--secondary)] text-[var(--secondary-foreground)]">
              <MapPinned size={11} />
            </span>
            Hard Constraints
          </span>
          <ChevronDown
            size={13}
            className={`transition-transform duration-200 ${constraintsOpen ? "rotate-180" : ""}`}
          />
        </button>

        <Collapsible open={constraintsOpen}>
          <div className="px-3 pb-3 space-y-2.5 border-t border-[var(--border)]">
            <div className="grid grid-cols-2 gap-2 pt-2.5">
              <div className="space-y-1">
                <label className="text-xs text-[var(--ink-muted)]">Location</label>
                <input
                  className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                  placeholder="NYC, remote US..."
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-[var(--ink-muted)]">Work Arrangement</label>
                <select
                  value={workArrangement}
                  onChange={(e) => setWorkArrangement(e.target.value as WorkArrangement | "")}
                  className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
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
              <label className="text-xs text-[var(--ink-muted)]">Seniority levels (comma-sep)</label>
              <input
                className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                placeholder="analyst, associate, avp, vp"
                value={seniority}
                onChange={(e) => setSeniority(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-[var(--ink-muted)]">Must include keywords (comma-sep)</label>
              <input
                className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                placeholder="market risk, quantitative"
                value={mustIncludeKeywords}
                onChange={(e) => setMustIncludeKeywords(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-[var(--ink-muted)]">Exclude role types (comma-sep)</label>
              <input
                className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                placeholder="model_validation, pure_audit"
                value={excludeRoleTypes}
                onChange={(e) => setExcludeRoleTypes(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-xs text-[var(--ink-muted)]">Compensation range</label>
                <input
                  className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                  placeholder="$120k–$160k"
                  value={compensationRange}
                  onChange={(e) => setCompensationRange(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-[var(--ink-muted)]">Visa note</label>
                <input
                  className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                  placeholder="H1B transfer only"
                  value={visaNote}
                  onChange={(e) => setVisaNote(e.target.value)}
                />
              </div>
            </div>
          </div>
        </Collapsible>
      </div>

      {/* Soft preferences (collapsible) */}
      <div className="border border-[var(--border)] rounded-lg">
        <button
          type="button"
          onClick={() => setSoftPreferencesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-[var(--ink-secondary)] hover:bg-[var(--muted)] rounded-lg transition-colors"
        >
          <span className="flex items-center gap-2">
            <span className="flex items-center justify-center w-5 h-5 rounded-full shrink-0 bg-[var(--secondary)] text-[var(--secondary-foreground)]">
              <Heart size={11} />
            </span>
            Soft Preferences
          </span>
          <ChevronDown
            size={13}
            className={`transition-transform duration-200 ${softPreferencesOpen ? "rotate-180" : ""}`}
          />
        </button>

        <Collapsible open={softPreferencesOpen}>
          <div className="px-3 pb-3 space-y-2 border-t border-[var(--border)] pt-2.5">
            <div className="space-y-1">
              <label className="text-xs text-[var(--ink-muted)]">Soft preferences (prefer / ideally)</label>
              <input
                className="w-full rounded border border-[var(--border)] bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/40"
                placeholder="prefer buy-side, market-facing analytics"
                value={softPreferences}
                onChange={(e) => setSoftPreferences(e.target.value)}
              />
              <p className="text-[10px] text-[var(--ink-muted)]">
                Influence ranking; use Exclude role types for hard exclusions.
              </p>
            </div>
          </div>
        </Collapsible>
      </div>

      {error && (
        <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
          {error}
        </p>
      )}

      <Button
        type="submit"
        disabled={!canSubmit}
        loading={loading}
        size="sm"
        className="w-full"
      >
        {!loading && <Play size={13} className="mr-1.5" />}
        Start Discovery Run
      </Button>
    </form>
  );
}
