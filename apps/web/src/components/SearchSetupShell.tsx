"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, getProfile, listRuns } from "@/api/client";
import type { ProfileRead, RunRead } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
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
  ChevronLeft,
  Sparkles,
  Search,
  FileText,
  Star,
  Inbox,
  Compass,
  Sliders,
  BookUser,
} from "lucide-react";
import { fmtTs } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type WizardPhase =
  | "source-select"
  | "criteria"
  | "depth-submit"
  | "polling"
  | "done"
  | "error";

type SearchSource = "profile_only" | "instruction_only" | "instruction_plus_profile";
type SearchMode = "direct" | "exploratory" | "profile_guided";
type SearchDepth = "quick" | "standard" | "deep";
type WorkArrangement = "hybrid" | "remote" | "onsite" | "any" | "";

const PROFILE_ONLY_REQUEST =
  "Find roles that match my candidate profile background, skills, and target positioning.";

const DEFAULT_PROFILE_SNIPPET =
  "Edit this profile to personalize your job discovery and fit analysis.";

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

function resolveSearchMode(source: SearchSource, criteriaMode: SearchMode): SearchMode {
  if (source === "profile_only") return "profile_guided";
  if (source === "instruction_plus_profile") return "profile_guided";
  return criteriaMode === "direct" ? "direct" : "exploratory";
}

function resolveRawRequest(source: SearchSource, userRequest: string): string {
  if (source === "profile_only") return PROFILE_ONLY_REQUEST;
  return userRequest.trim();
}

const SOURCE_OPTIONS: Array<{
  id: SearchSource;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}> = [
  {
    id: "instruction_plus_profile",
    icon: <Compass size={18} />,
    title: "Criteria + profile",
    subtitle: "Your direction leads; profile enriches search lanes",
  },
  {
    id: "instruction_only",
    icon: <Sliders size={18} />,
    title: "Criteria only",
    subtitle: "Search from your written criteria",
  },
  {
    id: "profile_only",
    icon: <BookUser size={18} />,
    title: "Profile only",
    subtitle: "Explore roles aligned with your saved profile",
  },
];

const HOW_IT_WORKS = [
  {
    icon: <Search size={16} className="text-[var(--primary)]" />,
    title: "Choose your search source",
    desc: "Pick profile-guided, criteria-only, or a combination based on how you want to search.",
  },
  {
    icon: <Sparkles size={16} className="text-amber-500" />,
    title: "Run discovery",
    desc: "The career-search agent browses job boards and company career pages.",
  },
  {
    icon: <Inbox size={16} className="text-emerald-500" />,
    title: "Review Role Inbox",
    desc: "Verified candidates land in your inbox — sort and analyze fit from there.",
  },
  {
    icon: <FileText size={16} className="text-blue-500" />,
    title: "Analyze fit",
    desc: "Generate Job Intelligence Reports and Fit Reports for decision-making.",
  },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SearchSetupShell() {
  const router = useRouter();
  const getToken = useApiToken();

  const [phase, setPhase] = useState<WizardPhase>("source-select");
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  const [searchSource, setSearchSource] = useState<SearchSource>("instruction_plus_profile");
  const [criteriaMode, setCriteriaMode] = useState<"direct" | "exploratory">("exploratory");
  const [rawUserRequest, setRawUserRequest] = useState("");
  const [searchDepth, setSearchDepth] = useState<SearchDepth>("standard");
  const [constraintsOpen, setConstraintsOpen] = useState(false);
  const [location, setLocation] = useState("");
  const [seniority, setSeniority] = useState("");
  const [excludeRoleTypes, setExcludeRoleTypes] = useState("");
  const [mustIncludeKeywords, setMustIncludeKeywords] = useState("");
  const [workArrangement, setWorkArrangement] = useState<WorkArrangement>("");
  const [visaNote, setVisaNote] = useState("");
  const [compensationRange, setCompensationRange] = useState("");
  const [softPreferences, setSoftPreferences] = useState("");
  const [softPreferencesOpen, setSoftPreferencesOpen] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollStatus, setPollStatus] = useState("");
  const [candidateCount, setCandidateCount] = useState<number | null>(null);

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

  useEffect(() => {
    getToken()
      .then((token) => getProfile(token))
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false));
  }, [getToken]);

  const profileNeedsSetup =
    !profile ||
    !profile.summary ||
    profile.summary.includes(DEFAULT_PROFILE_SNIPPET);

  const needsCriteria = searchSource !== "profile_only";
  const canProceedCriteria =
    !needsCriteria || rawUserRequest.trim().length >= 5;

  async function handleStartDiscovery() {
    if (!profile?.id) {
      setError("Set up your profile before starting discovery.");
      setPhase("error");
      return;
    }

    const request = resolveRawRequest(searchSource, rawUserRequest);
    if (request.length < 5) {
      setError("Please describe what you're looking for (at least 5 characters).");
      return;
    }

    setLoading(true);
    setError(null);
    setPhase("polling");
    setPollStatus("Starting discovery…");

    try {
      const token = await getToken();
      const run = await createRun(
        {
          run_type: "job_discovery",
          input_snapshot: {
            raw_user_request: request,
            search_mode: resolveSearchMode(searchSource, criteriaMode),
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
            profile_id: profile.id,
          },
        },
        token,
      );

      setPollStatus("Searching for roles…");
      const finished = await pollRunUntilDone(run.id, getToken);

      if (finished.status !== "succeeded") {
        throw new Error(finished.error_message ?? `Discovery ${finished.status.replace(/_/g, " ")}`);
      }

      const summary = finished.result_summary_json as Record<string, unknown> | null | undefined;
      const count =
        typeof summary?.candidate_count === "number"
          ? summary.candidate_count
          : Array.isArray(summary?.job_ids)
          ? summary.job_ids.length
          : null;

      setCandidateCount(count);
      setPhase("done");
      loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start discovery run");
      setPhase("error");
    } finally {
      setLoading(false);
    }
  }

  function resetWizard() {
    setPhase("source-select");
    setError(null);
    setCandidateCount(null);
    setPollStatus("");
  }

  // ---------------------------------------------------------------------------
  // Wizard card content
  // ---------------------------------------------------------------------------

  function renderWizardCard() {
    if (profileLoading) {
      return (
        <div className="rounded-xl border border-zinc-200 bg-white p-8 flex justify-center">
          <Loader2 size={20} className="animate-spin text-zinc-400" />
        </div>
      );
    }

    if (!profile) {
      return (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 space-y-3">
          <p className="text-sm text-amber-800">No profile found. Set up your candidate profile first.</p>
          <Link href="/profile">
            <Button size="sm">Set up Profile</Button>
          </Link>
        </div>
      );
    }

    if (phase === "polling") {
      return (
        <div className="rounded-xl border border-zinc-200 bg-white p-8 text-center space-y-4">
          <Loader2 size={28} className="animate-spin text-[var(--primary)] mx-auto" />
          <div>
            <p className="text-sm font-medium text-zinc-800">{pollStatus}</p>
            <p className="text-xs text-zinc-500 mt-1">This may take a few minutes.</p>
          </div>
        </div>
      );
    }

    if (phase === "done") {
      return (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-6 space-y-4">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={20} className="text-emerald-600" />
            <p className="text-sm font-semibold text-emerald-900">Discovery complete</p>
          </div>
          <p className="text-sm text-emerald-800">
            {candidateCount != null
              ? `${candidateCount} role${candidateCount === 1 ? "" : "s"} added to your Role Inbox.`
              : "New roles have been added to your Role Inbox."}
          </p>
          <div className="flex gap-2 flex-wrap">
            <Button size="sm" onClick={() => router.push("/jobs")}>
              Go to Role Inbox
            </Button>
            <Button size="sm" variant="outline" onClick={resetWizard}>
              Start another search
            </Button>
          </div>
        </div>
      );
    }

    if (phase === "error") {
      return (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 space-y-4">
          <p className="text-sm text-rose-800">{error ?? "Something went wrong."}</p>
          <Button size="sm" variant="outline" onClick={resetWizard}>
            Try again
          </Button>
        </div>
      );
    }

    if (phase === "source-select") {
      return (
        <div className="rounded-xl border border-zinc-200 bg-white p-6 space-y-5">
          <div>
            <h2 className="text-sm font-semibold text-zinc-800">Step 1 — Search source</h2>
            <p className="text-xs text-zinc-500 mt-1">What should drive this discovery run?</p>
          </div>

          {profileNeedsSetup && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              Your profile still looks like the default template.{" "}
              <Link href="/profile" className="font-medium underline">
                Personalize it
              </Link>{" "}
              for better profile-guided results.
            </div>
          )}

          <div className="rounded-lg border border-zinc-100 bg-zinc-50 px-4 py-3 text-xs text-zinc-600">
            <span className="font-medium text-zinc-700">Your profile:</span>{" "}
            {profile.summary?.slice(0, 80)}
            {profile.summary && profile.summary.length > 80 ? "…" : ""}
            {" · "}
            <Link href="/profile" className="text-[var(--primary)] hover:underline">
              Edit
            </Link>
          </div>

          <div className="space-y-2">
            {SOURCE_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSearchSource(opt.id)}
                className={[
                  "w-full flex items-start gap-3 p-3 rounded-lg border text-left transition-all",
                  searchSource === opt.id
                    ? "border-[var(--primary)] bg-[var(--secondary)]"
                    : "border-zinc-200 hover:border-zinc-300 bg-white",
                ].join(" ")}
              >
                <span className={searchSource === opt.id ? "text-[var(--primary)]" : "text-zinc-400"}>
                  {opt.icon}
                </span>
                <span>
                  <span className="block text-sm font-medium text-zinc-800">{opt.title}</span>
                  <span className="block text-xs text-zinc-500 mt-0.5">{opt.subtitle}</span>
                </span>
              </button>
            ))}
          </div>

          <Button
            className="w-full"
            onClick={() => setPhase(needsCriteria ? "criteria" : "depth-submit")}
          >
            Continue
            <ChevronRight size={14} className="ml-1" />
          </Button>
        </div>
      );
    }

    if (phase === "criteria") {
      return (
        <div className="rounded-xl border border-zinc-200 bg-white p-6 space-y-5">
          <div>
            <h2 className="text-sm font-semibold text-zinc-800">Step 2 — Search criteria</h2>
            <p className="text-xs text-zinc-500 mt-1">Describe the roles you want to find.</p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-zinc-700">
              What are you looking for?{" "}
              <span className="text-rose-400 font-normal">required</span>
            </label>
            <textarea
              rows={4}
              placeholder="e.g. Market risk VP roles at mid-size banks in NYC, quantitative background preferred..."
              value={rawUserRequest}
              onChange={(e) => setRawUserRequest(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/40 focus:bg-white transition-colors resize-none"
            />
            <p className="text-xs text-zinc-400">
              {rawUserRequest.trim().length < 5
                ? `${5 - rawUserRequest.trim().length} more characters needed`
                : `${rawUserRequest.trim().length} characters`}
            </p>
          </div>

          {searchSource === "instruction_only" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-zinc-700">Search style</label>
              <div className="grid grid-cols-2 gap-2">
                {(["direct", "exploratory"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setCriteriaMode(mode)}
                    className={[
                      "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                      criteriaMode === mode
                        ? "border-[var(--primary)] bg-[var(--primary)] text-white font-medium"
                        : "border-zinc-200 text-zinc-600 hover:border-zinc-400 bg-white",
                    ].join(" ")}
                  >
                    <span className="block font-medium capitalize">{mode}</span>
                    <span
                      className={[
                        "block text-[11px] mt-0.5",
                        criteriaMode === mode ? "text-white/60" : "text-zinc-400",
                      ].join(" ")}
                    >
                      {mode === "direct" ? "Exact match" : "Broader search"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {renderConstraintsSection()}
          {renderSoftPreferencesSection()}

          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => setPhase("source-select")}>
              <ChevronLeft size={14} className="mr-1" />
              Back
            </Button>
            <Button
              className="flex-1"
              disabled={!canProceedCriteria}
              onClick={() => setPhase("depth-submit")}
            >
              Continue
              <ChevronRight size={14} className="ml-1" />
            </Button>
          </div>
        </div>
      );
    }

    // depth-submit
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-6 space-y-5">
        <div>
          <h2 className="text-sm font-semibold text-zinc-800">Step 3 — Depth & launch</h2>
          <p className="text-xs text-zinc-500 mt-1">How thoroughly should the agent search?</p>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium text-zinc-700">Search Depth</label>
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                { val: "quick" as const, hint: "~20 candidates" },
                { val: "standard" as const, hint: "~50 candidates" },
                { val: "deep" as const, hint: "~100 candidates" },
              ] as const
            ).map(({ val, hint }) => (
              <button
                key={val}
                type="button"
                onClick={() => setSearchDepth(val)}
                className={[
                  "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                  searchDepth === val
                    ? "border-[var(--primary)] bg-[var(--primary)] text-white font-medium"
                    : "border-zinc-200 text-zinc-600 hover:border-zinc-400 bg-white",
                ].join(" ")}
              >
                <span className="block font-medium capitalize">{val}</span>
                <span
                  className={[
                    "block text-[11px] mt-0.5",
                    searchDepth === val ? "text-white/60" : "text-zinc-400",
                  ].join(" ")}
                >
                  {hint}
                </span>
              </button>
            ))}
          </div>
        </div>

        {searchSource === "profile_only" && (
          <>
            {renderConstraintsSection()}
            {renderSoftPreferencesSection()}
          </>
        )}

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => setPhase(needsCriteria ? "criteria" : "source-select")}
          >
            <ChevronLeft size={14} className="mr-1" />
            Back
          </Button>
          <Button className="flex-1" disabled={loading} onClick={handleStartDiscovery}>
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin mr-2" />
                Starting…
              </>
            ) : (
              <>
                <Play size={14} className="mr-2" />
                Start Discovery
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  function renderConstraintsSection() {
    return (
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
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
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
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
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
              <label className="text-xs font-medium text-zinc-500">Seniority (comma-separated)</label>
              <input
                className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                placeholder="analyst, associate, avp, vp"
                value={seniority}
                onChange={(e) => setSeniority(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-zinc-500">Must include keywords</label>
              <input
                className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                placeholder="market risk, quantitative"
                value={mustIncludeKeywords}
                onChange={(e) => setMustIncludeKeywords(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-zinc-500">Exclude role types</label>
              <input
                className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                placeholder="model_validation, pure_audit"
                value={excludeRoleTypes}
                onChange={(e) => setExcludeRoleTypes(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-zinc-500">Compensation range</label>
                <input
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                  placeholder="$120k–$160k"
                  value={compensationRange}
                  onChange={(e) => setCompensationRange(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-zinc-500">Visa note</label>
                <input
                  className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                  placeholder="H1B transfer only"
                  value={visaNote}
                  onChange={(e) => setVisaNote(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  function renderSoftPreferencesSection() {
    return (
      <div className="rounded-lg border border-zinc-200 overflow-hidden">
        <button
          type="button"
          onClick={() => setSoftPreferencesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-zinc-600 hover:bg-zinc-50 transition-colors"
        >
          <span>Soft Preferences</span>
          <span className="flex items-center gap-1 text-xs text-zinc-400">
            {softPreferencesOpen ? "hide" : "show"}
            {softPreferencesOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </span>
        </button>

        {softPreferencesOpen && (
          <div className="px-4 pb-4 space-y-2 border-t border-zinc-100 bg-zinc-50 pt-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-zinc-500">
                Soft preferences (prefer / ideally)
              </label>
              <input
                className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/50"
                placeholder="prefer buy-side, market-facing analytics, automation-heavy workflow"
                value={softPreferences}
                onChange={(e) => setSoftPreferences(e.target.value)}
              />
              <p className="text-[11px] text-zinc-400">
                Influence ranking and expansion; do not exclude jobs. Use &quot;Exclude role
                types&quot; for hard exclusions.
              </p>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-10">
      <div>
        <h1 className="text-2xl font-bold text-zinc-900">Search Setup</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Choose a profile, set your direction, and launch discovery into your Role Inbox.
        </p>
      </div>

      {renderWizardCard()}

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
                href={run.status === "succeeded" ? "/jobs" : `/runs/${run.id}`}
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

      <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Star size={13} className="text-zinc-400 shrink-0" />
          <p className="text-xs text-zinc-500">
            After discovery, review roles in{" "}
            <Link href="/jobs" className="font-medium text-[var(--primary)] hover:underline">
              Role Inbox
            </Link>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
