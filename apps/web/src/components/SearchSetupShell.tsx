"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, listRuns } from "@/api/client";
import type { RunRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  Play,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Circle,
  AlertCircle,
  Clock,
  ChevronRight,
  Sparkles,
  Search,
  FileText,
  Star,
  Inbox,
} from "lucide-react";
import { fmtTs } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SearchMode = "direct" | "exploratory";
type SearchDepth = "quick" | "standard" | "deep";
type WorkArrangement = "hybrid" | "remote" | "onsite" | "any" | "";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function csvToList(val: string): string[] {
  return val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "In Progress",
  succeeded: "Completed",
  failed: "Failed",
  needs_review: "Needs Review",
  cancelled: "Cancelled",
};

function humanStatus(s: string) {
  return STATUS_LABELS[s] ?? s.replace(/_/g, " ");
}

function statusBadgeClass(status: string): string {
  if (status === "succeeded") return "bg-emerald-100 text-emerald-700";
  if (status === "running") return "bg-blue-100 text-blue-700";
  if (status === "queued") return "bg-zinc-100 text-zinc-600";
  if (status === "needs_review") return "bg-amber-100 text-amber-700";
  if (status === "failed") return "bg-rose-100 text-rose-700";
  return "bg-zinc-100 text-zinc-500";
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={13} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={13} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={13} className="text-blue-500 animate-pulse shrink-0" />;
  return <Clock size={13} className="text-zinc-400 shrink-0" />;
}

// ---------------------------------------------------------------------------
// How it works steps
// ---------------------------------------------------------------------------

const HOW_IT_WORKS = [
  {
    icon: <Search size={16} className="text-indigo-500" />,
    title: "Translate your direction",
    desc: "The agent understands your natural language search request and identifies target roles and companies.",
  },
  {
    icon: <Sparkles size={16} className="text-amber-500" />,
    title: "Run discovery",
    desc: "The career-search agent browses job boards and company career pages, logging every candidate it finds.",
  },
  {
    icon: <Inbox size={16} className="text-emerald-500" />,
    title: "Add roles to Role Inbox",
    desc: "Verified candidates are persisted to your Role Inbox — every job is traceable to a source and ledger entry.",
  },
  {
    icon: <FileText size={16} className="text-blue-500" />,
    title: "Review and analyze",
    desc: "Generate a Job Intelligence Report or Fit Analysis for any role in your inbox.",
  },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SearchSetupShell() {
  const router = useRouter();
  const getToken = useApiToken();

  // Form state
  const [rawUserRequest, setRawUserRequest] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("exploratory");
  const [searchDepth, setSearchDepth] = useState<SearchDepth>("standard");
  const [constraintsOpen, setConstraintsOpen] = useState(false);
  const [location, setLocation] = useState("");
  const [seniority, setSeniority] = useState("");
  const [excludeRoleTypes, setExcludeRoleTypes] = useState("");
  const [mustIncludeKeywords, setMustIncludeKeywords] = useState("");
  const [workArrangement, setWorkArrangement] = useState<WorkArrangement>("");
  const [visaNote, setVisaNote] = useState("");
  const [compensationRange, setCompensationRange] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Recent runs
  const [recentRuns, setRecentRuns] = useState<RunRead[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);

  const loadRuns = useCallback(() => {
    setRunsLoading(true);
    getToken()
      .then((token) => listRuns(token))
      .then((list) => {
        const discovery = list.items
          .filter((r) => r.run_type === "job_discovery")
          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          .slice(0, 6);
        setRecentRuns(discovery);
      })
      .catch(() => {})
      .finally(() => setRunsLoading(false));
  }, [getToken]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const canSubmit = rawUserRequest.trim().length >= 5;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || loading) return;

    setLoading(true);
    setError(null);

    try {
      const token = await getToken();
      const run = await createRun(
        {
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
            profile_id: undefined,
          },
        },
        token,
      );
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start discovery run");
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-zinc-900">Search Setup</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Describe what you&apos;re looking for. The career search agent will find and log matching roles.
        </p>
      </div>

      {/* Discovery form */}
      <form onSubmit={handleSubmit} className="rounded-xl border border-zinc-200 bg-white p-6 space-y-5">
        <div className="flex items-center gap-2 pb-3 border-b border-zinc-100">
          <div className="w-7 h-7 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
            <Search size={14} className="text-indigo-600" />
          </div>
          <h2 className="text-sm font-semibold text-zinc-800">New Discovery Run</h2>
        </div>

        {/* Search request */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-zinc-700">
            What are you looking for?{" "}
            <span className="text-rose-400 font-normal">required</span>
          </label>
          <textarea
            rows={4}
            required
            minLength={5}
            placeholder="e.g. Looking for market risk roles at mid-size banks in NYC, ideally VP or SVP level, quantitative background preferred..."
            value={rawUserRequest}
            onChange={(e) => setRawUserRequest(e.target.value)}
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:bg-white transition-colors resize-none"
          />
          <p className="text-xs text-zinc-400">
            {rawUserRequest.trim().length < 5
              ? `${5 - rawUserRequest.trim().length} more characters needed`
              : `${rawUserRequest.trim().length} characters`}
          </p>
        </div>

        {/* Search mode */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-zinc-700">Search Mode</label>
          <div className="grid grid-cols-3 gap-2">
            {(["direct", "exploratory"] as SearchMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setSearchMode(mode)}
                className={[
                  "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                  searchMode === mode
                    ? "border-indigo-600 bg-indigo-600 text-white font-medium"
                    : "border-zinc-200 text-zinc-600 hover:border-zinc-400 bg-white",
                ].join(" ")}
              >
                <span className="block font-medium capitalize">{mode}</span>
                <span className={["block text-[11px] mt-0.5", searchMode === mode ? "text-indigo-200" : "text-zinc-400"].join(" ")}>
                  {mode === "direct" ? "Exact match" : "Broader search"}
                </span>
              </button>
            ))}
            <button
              type="button"
              disabled
              title="Requires a saved profile"
              className="py-2 px-3 text-sm rounded-lg border border-zinc-100 text-zinc-300 cursor-not-allowed text-left"
            >
              <span className="block font-medium">Profile-guided</span>
              <span className="block text-[11px] mt-0.5 text-zinc-300">Coming soon</span>
            </button>
          </div>
        </div>

        {/* Search depth */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-zinc-700">Search Depth</label>
          <div className="grid grid-cols-3 gap-2">
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
                  "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                  searchDepth === val
                    ? "border-indigo-600 bg-indigo-600 text-white font-medium"
                    : "border-zinc-200 text-zinc-600 hover:border-zinc-400 bg-white",
                ].join(" ")}
              >
                <span className="block font-medium capitalize">{val}</span>
                <span className={["block text-[11px] mt-0.5", searchDepth === val ? "text-indigo-200" : "text-zinc-400"].join(" ")}>
                  {hint}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Hard constraints (collapsible) */}
        <div className="rounded-lg border border-zinc-200 overflow-hidden">
          <button
            type="button"
            onClick={() => setConstraintsOpen((o) => !o)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-zinc-600 hover:bg-zinc-50 transition-colors"
          >
            <span>Hard Constraints</span>
            <span className="flex items-center gap-1 text-xs text-zinc-400">
              {constraintsOpen ? "hide" : "show"}
              {constraintsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </span>
          </button>

          {constraintsOpen && (
            <div className="px-4 pb-4 space-y-3 border-t border-zinc-100 bg-zinc-50">
              <div className="grid grid-cols-2 gap-3 pt-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-zinc-500">Location</label>
                  <input
                    className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    placeholder="NYC, remote US..."
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-zinc-500">Work Arrangement</label>
                  <select
                    value={workArrangement}
                    onChange={(e) => setWorkArrangement(e.target.value as WorkArrangement)}
                    className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
                <label className="text-xs font-medium text-zinc-500">Seniority levels (comma-separated)</label>
                <input
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="analyst, associate, avp, vp"
                  value={seniority}
                  onChange={(e) => setSeniority(e.target.value)}
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-zinc-500">Must include keywords (comma-separated)</label>
                <input
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="market risk, quantitative"
                  value={mustIncludeKeywords}
                  onChange={(e) => setMustIncludeKeywords(e.target.value)}
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-zinc-500">Exclude role types (comma-separated)</label>
                <input
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  placeholder="model_validation, pure_audit"
                  value={excludeRoleTypes}
                  onChange={(e) => setExcludeRoleTypes(e.target.value)}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-zinc-500">Compensation range</label>
                  <input
                    className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    placeholder="$120k–$160k"
                    value={compensationRange}
                    onChange={(e) => setCompensationRange(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-zinc-500">Visa note</label>
                  <input
                    className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <Button
          type="submit"
          disabled={loading || !canSubmit}
          className="w-full"
        >
          {loading ? (
            <>
              <Loader2 size={14} className="animate-spin mr-2" />
              Starting discovery run…
            </>
          ) : (
            <>
              <Play size={14} className="mr-2" />
              Start Discovery Run
            </>
          )}
        </Button>
      </form>

      {/* How it works */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold text-zinc-700 uppercase tracking-wider">How it works</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {HOW_IT_WORKS.map((step, i) => (
            <div
              key={i}
              className="flex items-start gap-3 rounded-lg border border-zinc-200 bg-white p-4"
            >
              <div className="w-8 h-8 rounded-lg bg-zinc-50 border border-zinc-100 flex items-center justify-center shrink-0">
                {step.icon}
              </div>
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">
                    {i + 1}
                  </span>
                  <p className="text-sm font-medium text-zinc-800">{step.title}</p>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent discovery runs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-700 uppercase tracking-wider">Recent Searches</h2>
          <Link href="/runs" className="text-xs text-zinc-400 hover:text-zinc-700 transition-colors">
            View all →
          </Link>
        </div>

        {runsLoading && (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-14 rounded-lg border border-zinc-100 bg-zinc-50 animate-pulse" />
            ))}
          </div>
        )}

        {!runsLoading && recentRuns.length === 0 && (
          <div className="rounded-lg border border-dashed border-zinc-200 py-8 text-center">
            <p className="text-xs text-zinc-400">No discovery runs yet. Start your first search above.</p>
          </div>
        )}

        {!runsLoading && recentRuns.length > 0 && (
          <div className="rounded-xl border border-zinc-200 bg-white divide-y divide-zinc-100 overflow-hidden">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={`/runs/${run.id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-zinc-50 transition-colors"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <StatusIcon status={run.status} />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-zinc-700 truncate">Discovery Run</p>
                    <p className="text-[10px] text-zinc-400">{fmtTs(run.created_at)}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge className={statusBadgeClass(run.status) + " text-[10px]"}>
                    {humanStatus(run.status)}
                  </Badge>
                  <ChevronRight size={13} className="text-zinc-300" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Quick actions footer */}
      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Star size={13} className="text-zinc-400 shrink-0" />
          <p className="text-xs text-zinc-500">
            After discovery, go to{" "}
            <Link href="/jobs" className="font-medium text-indigo-600 hover:underline">
              Role Inbox
            </Link>{" "}
            to view and analyze found roles.
          </p>
        </div>
      </div>
    </div>
  );
}
