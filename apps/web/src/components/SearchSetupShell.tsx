"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { createRun, getProfile, listProfiles, listRuns, updateSearchDefaults } from "@/api/client";
import type { ProfileRead, RunRead } from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Select } from "@/components/ui/select";
import { PageContainer } from "@/components/ui/page-container";
import { PageHeader } from "@/components/ui/page-header";
import { ZoneHead } from "@/components/ui/zone-head";
import { Banner } from "@/components/ui/banner";
import { Card } from "@/components/ui/card";
import { Row } from "@/components/ui/row";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Collapsible } from "@/components/Collapsible";
import { EmptyState } from "@/components/EmptyState";
import { RunRow } from "@/components/RunRow";
import {
  Loader2,
  Play,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
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
  History,
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

const STATUS_KEY_MAP: Record<string, string> = {
  queued: "statusQueued",
  running: "statusRunning",
  succeeded: "statusSucceeded",
  failed: "statusFailed",
  needs_review: "statusNeedsReview",
  cancelled: "statusCancelled",
};

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
  titleKey: string;
  subtitleKey: string;
}> = [
  {
    id: "instruction_plus_profile",
    icon: <Compass size={18} />,
    titleKey: "sourceCriteriaProfileTitle",
    subtitleKey: "sourceCriteriaProfileSubtitle",
  },
  {
    id: "instruction_only",
    icon: <Sliders size={18} />,
    titleKey: "sourceCriteriaOnlyTitle",
    subtitleKey: "sourceCriteriaOnlySubtitle",
  },
  {
    id: "profile_only",
    icon: <BookUser size={18} />,
    titleKey: "sourceProfileOnlyTitle",
    subtitleKey: "sourceProfileOnlySubtitle",
  },
];

const HOW_IT_WORKS = [
  {
    icon: <Search size={16} className="text-[var(--primary)]" />,
    titleKey: "step1HowTitle",
    descKey: "step1HowDesc",
  },
  {
    icon: <Sparkles size={16} className="text-amber-500" />,
    titleKey: "step2HowTitle",
    descKey: "step2HowDesc",
  },
  {
    icon: <Inbox size={16} className="text-emerald-500" />,
    titleKey: "step3HowTitle",
    descKey: "step3HowDesc",
  },
  {
    icon: <FileText size={16} className="text-blue-500" />,
    titleKey: "step4HowTitle",
    descKey: "step4HowDesc",
  },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SearchSetupShell() {
  const t = useTranslations("searchSetup");
  const tRuns = useTranslations("runs");
  const router = useRouter();
  const getToken = useApiToken();

  const [phase, setPhase] = useState<WizardPhase>("source-select");
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  const [allProfiles, setAllProfiles] = useState<ProfileRead[]>([]);
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

  function applySearchDefaults(defaults: Record<string, unknown> | null | undefined) {
    if (!defaults) return;
    if (defaults.search_source) setSearchSource(defaults.search_source as SearchSource);
    if (defaults.search_depth) setSearchDepth(defaults.search_depth as SearchDepth);
    if (typeof defaults.location === "string") setLocation(defaults.location);
    if (typeof defaults.seniority === "string") setSeniority(defaults.seniority);
    if (typeof defaults.exclude_role_types === "string") setExcludeRoleTypes(defaults.exclude_role_types);
    if (typeof defaults.must_include_keywords === "string") setMustIncludeKeywords(defaults.must_include_keywords);
    if (typeof defaults.work_arrangement === "string") setWorkArrangement(defaults.work_arrangement as WorkArrangement);
    if (typeof defaults.visa_note === "string") setVisaNote(defaults.visa_note);
    if (typeof defaults.compensation_range === "string") setCompensationRange(defaults.compensation_range);
    if (typeof defaults.soft_preferences === "string") setSoftPreferences(defaults.soft_preferences);
    if (defaults.location || defaults.seniority || defaults.exclude_role_types ||
        defaults.must_include_keywords || defaults.work_arrangement || defaults.visa_note ||
        defaults.compensation_range) {
      setConstraintsOpen(true);
    }
    if (defaults.soft_preferences) setSoftPreferencesOpen(true);
  }

  function collectSearchDefaults(): Record<string, string> {
    return {
      search_source: searchSource,
      search_depth: searchDepth,
      location,
      seniority,
      exclude_role_types: excludeRoleTypes,
      must_include_keywords: mustIncludeKeywords,
      work_arrangement: workArrangement,
      visa_note: visaNote,
      compensation_range: compensationRange,
      soft_preferences: softPreferences,
    };
  }

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
      .then(async (token) => {
        const profiles = await listProfiles(token).catch(() => [] as ProfileRead[]);
        setAllProfiles(profiles);
        if (profiles.length > 0) {
          setProfile(profiles[0]);
          applySearchDefaults((profiles[0] as ProfileRead & { search_defaults?: Record<string, unknown> }).search_defaults);
        } else {
          const defaultProfile = await getProfile(token).catch(() => null);
          if (defaultProfile) {
            setProfile(defaultProfile);
            setAllProfiles([defaultProfile]);
            applySearchDefaults((defaultProfile as ProfileRead & { search_defaults?: Record<string, unknown> }).search_defaults);
          }
        }
      })
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setError(t("setProfileBeforeStarting"));
      setPhase("error");
      return;
    }

    const request = resolveRawRequest(searchSource, rawUserRequest);
    if (request.length < 5) {
      setError(t("describeWhatLooking"));
      return;
    }

    setLoading(true);
    setError(null);
    setPhase("polling");
    setPollStatus(t("startingDiscoveryEllipsis"));

    try {
      const token = await getToken();

      // Fire-and-forget: save current search preferences to the selected profile
      updateSearchDefaults(profile.id, collectSearchDefaults(), token).catch(() => {});

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

      setPollStatus(t("searchingForRoles"));
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
      setError(err instanceof Error ? err.message : t("failedToStartDiscovery"));
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
        <Card className="p-[var(--space-surface-spacious)] space-y-[var(--space-stack-md)]">
          <div className="flex items-start gap-2.5">
            <Skeleton className="w-6 h-6 rounded-full shrink-0" />
            <div className="space-y-1.5 flex-1">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
          <Skeleton className="h-16 w-full rounded-lg" />
          <div className="space-y-2">
            <Skeleton className="h-12 w-full rounded-lg" />
            <Skeleton className="h-12 w-full rounded-lg" />
            <Skeleton className="h-12 w-full rounded-lg" />
          </div>
        </Card>
      );
    }

    if (!profile) {
      return (
        <Banner
          variant="warn"
          size="lg"
          action={
            <Link href="/profile">
              <Button size="sm">{t("setUpProfile")}</Button>
            </Link>
          }
        >
          {t("noProfileFound")}
        </Banner>
      );
    }

    if (phase === "polling") {
      return (
        <Card className="p-[var(--space-surface-spacious)] text-center space-y-4">
          <Loader2 size={28} className="animate-spin text-[var(--primary)] mx-auto" />
          <div>
            <p className="text-sm font-medium text-[var(--ink-primary)]">{pollStatus}</p>
            <p className="text-xs text-[var(--ink-muted)] mt-1">{t("thisMayTakeAFewMinutes")}</p>
          </div>
        </Card>
      );
    }

    if (phase === "done") {
      return (
        <Banner
          variant="success"
          size="lg"
          icon={CheckCircle2}
          title={t("discoveryComplete")}
          action={
            <div className="flex gap-2 flex-wrap">
              <Button size="sm" onClick={() => router.push("/jobs")}>
                {t("goToRoleInbox")}
              </Button>
              <Button size="sm" variant="outline" onClick={resetWizard}>
                {t("startAnotherSearch")}
              </Button>
            </div>
          }
        >
          <p className="mt-[var(--space-stack-xs)]">
            {candidateCount != null
              ? t("rolesAdded", { count: candidateCount })
              : t("newRolesAdded")}
          </p>
        </Banner>
      );
    }

    if (phase === "error") {
      return (
        <Banner
          variant="danger"
          size="lg"
          action={
            <Button size="sm" variant="outline" onClick={resetWizard}>
              {t("tryAgain")}
            </Button>
          }
        >
          {error ?? t("somethingWentWrong")}
        </Banner>
      );
    }

    if (phase === "source-select") {
      return (
        <Card className="p-[var(--space-surface-spacious)] space-y-[var(--space-stack-md)]">
          <ZoneHead variant="step" step={1} title={t("step1Title")} sub={t("step1Subtitle")} />

          {profileNeedsSetup && (
            <Banner variant="warn">
              {t("profileDefaultWarning")}{" "}
              <Link href="/profile" className="font-medium underline">
                {t("personalizeIt")}
              </Link>{" "}
              {t("forBetterResults")}
            </Banner>
          )}

          <Row className="space-y-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-[var(--ink-secondary)]">
                {allProfiles.length > 1 ? t("selectedProfile") : t("yourProfile")}
              </span>
              <Link href="/profile" className="text-[var(--primary)] hover:underline">
                {t("edit")}
              </Link>
            </div>
            {allProfiles.length > 1 && (
              <Select
                size="sm"
                value={profile.id}
                onValueChange={(id) => {
                  const p = allProfiles.find((x) => x.id === id);
                  if (p) {
                    setProfile(p);
                    applySearchDefaults((p as ProfileRead & { search_defaults?: Record<string, unknown> }).search_defaults);
                  }
                }}
                options={allProfiles.map((p) => ({
                  value: p.id,
                  label:
                    (p.label || t("profileFallback", { id: p.id.slice(0, 8) })) +
                    (p.summary ? ` — ${p.summary.slice(0, 50)}` : ""),
                }))}
              />
            )}
            {allProfiles.length <= 1 && (
              <div>
                {profile.summary?.slice(0, 80)}
                {profile.summary && profile.summary.length > 80 ? "…" : ""}
              </div>
            )}
          </Row>

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
                    : "border-[var(--border)] hover:border-[var(--ink-faint)] bg-white",
                ].join(" ")}
              >
                <span className={searchSource === opt.id ? "text-[var(--primary)]" : "text-[var(--ink-muted)]"}>
                  {opt.icon}
                </span>
                <span>
                  <span className="block text-sm font-medium text-[var(--ink-primary)]">{t(opt.titleKey)}</span>
                  <span className="block text-xs text-[var(--ink-muted)] mt-0.5">{t(opt.subtitleKey)}</span>
                </span>
              </button>
            ))}
          </div>

          <Button
            className="w-full"
            onClick={() => setPhase(needsCriteria ? "criteria" : "depth-submit")}
          >
            {t("continueBtn")}
            <ChevronRight size={14} className="ml-1" />
          </Button>
        </Card>
      );
    }

    if (phase === "criteria") {
      return (
        <Card className="p-[var(--space-surface-spacious)] space-y-[var(--space-stack-md)]">
          <ZoneHead variant="step" step={2} title={t("step2Title")} sub={t("step2Subtitle")} />

          <div>
            <Field label={t("whatLookingFor")} required={t("required")}>
              <Textarea
                rows={4}
                resize="none"
                placeholder={t("criteriaPlaceholder")}
                value={rawUserRequest}
                onChange={(e) => setRawUserRequest(e.target.value)}
              />
            </Field>
            <p className="text-xs text-[var(--ink-muted)] mt-1.5">
              {rawUserRequest.trim().length < 5
                ? t("moreCharsNeeded", { count: 5 - rawUserRequest.trim().length })
                : t("charsCount", { count: rawUserRequest.trim().length })}
            </p>
          </div>

          {searchSource === "instruction_only" && (
            <Field label={t("searchStyle")}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {(["direct", "exploratory"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setCriteriaMode(mode)}
                    className={[
                      "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                      criteriaMode === mode
                        ? "border-[var(--primary)] bg-[var(--secondary)]"
                        : "border-[var(--border)] hover:border-[var(--ink-faint)] bg-white",
                    ].join(" ")}
                  >
                    <span className="block font-medium text-[var(--ink-primary)]">
                      {mode === "direct" ? t("modeDirectLabel") : t("modeExploratoryLabel")}
                    </span>
                    <span className="block text-2xs mt-0.5 text-[var(--ink-muted)]">
                      {mode === "direct" ? t("exactMatch") : t("broaderSearch")}
                    </span>
                  </button>
                ))}
              </div>
            </Field>
          )}

          {renderConstraintsSection()}
          {renderSoftPreferencesSection()}

          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => setPhase("source-select")}>
              <ChevronLeft size={14} className="mr-1" />
              {t("back")}
            </Button>
            <Button
              className="flex-1"
              disabled={!canProceedCriteria}
              onClick={() => setPhase("depth-submit")}
            >
              {t("continueBtn")}
              <ChevronRight size={14} className="ml-1" />
            </Button>
          </div>
        </Card>
      );
    }

    // depth-submit
    return (
      <Card className="p-[var(--space-surface-spacious)] space-y-[var(--space-stack-md)]">
        <ZoneHead variant="step" step={3} title={t("step3Title")} sub={t("step3Subtitle")} />

        <Field label={t("searchDepthLabel")}>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {(
              [
                { val: "quick" as const, labelKey: "depthQuickLabel", hintKey: "depthQuickHint" },
                { val: "standard" as const, labelKey: "depthStandardLabel", hintKey: "depthStandardHint" },
                { val: "deep" as const, labelKey: "depthDeepLabel", hintKey: "depthDeepHint" },
              ] as const
            ).map(({ val, labelKey, hintKey }) => (
              <button
                key={val}
                type="button"
                onClick={() => setSearchDepth(val)}
                className={[
                  "py-2 px-3 text-sm rounded-lg border transition-all text-left",
                  searchDepth === val
                    ? "border-[var(--primary)] bg-[var(--secondary)]"
                    : "border-[var(--border)] hover:border-[var(--ink-faint)] bg-white",
                ].join(" ")}
              >
                <span className="block font-medium text-[var(--ink-primary)]">{t(labelKey)}</span>
                <span className="block text-2xs mt-0.5 text-[var(--ink-muted)]">
                  {t(hintKey)}
                </span>
              </button>
            ))}
          </div>
        </Field>

        {searchSource === "profile_only" && (
          <>
            {renderConstraintsSection()}
            {renderSoftPreferencesSection()}
          </>
        )}

        {error && <Banner variant="danger">{error}</Banner>}

        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => setPhase(needsCriteria ? "criteria" : "source-select")}
          >
            <ChevronLeft size={14} className="mr-1" />
            {t("back")}
          </Button>
          <Button className="flex-1" loading={loading} shimmer onClick={handleStartDiscovery}>
            {loading ? (
              t("starting")
            ) : (
              <>
                <Play size={14} className="mr-2" />
                {t("startDiscovery")}
              </>
            )}
          </Button>
        </div>
      </Card>
    );
  }

  function renderConstraintsSection() {
    return (
      <div className="rounded-lg border border-[var(--border)] overflow-hidden">
        <button
          type="button"
          onClick={() => setConstraintsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--muted)] transition-colors"
        >
          <span>{t("hardConstraints")}</span>
          <span className="flex items-center gap-1 text-xs text-[var(--ink-muted)]">
            {constraintsOpen ? t("hide") : t("show")}
            {constraintsOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </span>
        </button>

        <Collapsible open={constraintsOpen}>
          <div className="px-4 pb-4 space-y-3 border-t border-[var(--border)] bg-[var(--muted)]">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-3">
              <Field size="sm" label={t("location")}>
                <Input
                  size="sm"
                  placeholder={t("locationPlaceholder")}
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </Field>
              <Field size="sm" label={t("workArrangement")}>
                <Select
                  size="sm"
                  value={workArrangement}
                  onValueChange={(v) => setWorkArrangement(v as WorkArrangement)}
                  options={[
                    { value: "", label: t("noPreference") },
                    { value: "hybrid", label: t("hybrid") },
                    { value: "remote", label: t("remote") },
                    { value: "onsite", label: t("onsite") },
                    { value: "any", label: t("any") },
                  ]}
                />
              </Field>
            </div>

            <Field size="sm" label={t("seniorityCsv")}>
              <Input
                size="sm"
                placeholder={t("seniorityPlaceholder")}
                value={seniority}
                onChange={(e) => setSeniority(e.target.value)}
              />
            </Field>

            <Field size="sm" label={t("mustIncludeKeywords")}>
              <Input
                size="sm"
                placeholder={t("mustIncludePlaceholder")}
                value={mustIncludeKeywords}
                onChange={(e) => setMustIncludeKeywords(e.target.value)}
              />
            </Field>

            <Field size="sm" label={t("excludeRoleTypes")}>
              <Input
                size="sm"
                placeholder={t("excludePlaceholder")}
                value={excludeRoleTypes}
                onChange={(e) => setExcludeRoleTypes(e.target.value)}
              />
            </Field>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field size="sm" label={t("compensationRange")}>
                <Input
                  size="sm"
                  placeholder={t("compensationPlaceholder")}
                  value={compensationRange}
                  onChange={(e) => setCompensationRange(e.target.value)}
                />
              </Field>
              <Field size="sm" label={t("visaNote")}>
                <Input
                  size="sm"
                  placeholder={t("visaPlaceholder")}
                  value={visaNote}
                  onChange={(e) => setVisaNote(e.target.value)}
                />
              </Field>
            </div>
          </div>
        </Collapsible>
      </div>
    );
  }

  function renderSoftPreferencesSection() {
    return (
      <div className="rounded-lg border border-[var(--border)] overflow-hidden">
        <button
          type="button"
          onClick={() => setSoftPreferencesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--muted)] transition-colors"
        >
          <span>{t("softPreferences")}</span>
          <span className="flex items-center gap-1 text-xs text-[var(--ink-muted)]">
            {softPreferencesOpen ? t("hide") : t("show")}
            {softPreferencesOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </span>
        </button>

        <Collapsible open={softPreferencesOpen}>
          <div className="px-4 pb-4 space-y-2 border-t border-[var(--border)] bg-[var(--muted)] pt-3">
            <Field
              size="sm"
              label={t("softPreferencesLabel")}
              footnote={t("softPreferencesHint")}
            >
              <Input
                size="sm"
                placeholder={t("softPreferencesPlaceholder")}
                value={softPreferences}
                onChange={(e) => setSoftPreferences(e.target.value)}
              />
            </Field>
          </div>
        </Collapsible>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
    <PageContainer variant="narrow" className="space-y-[var(--space-stack-xl)]">
      <PageHeader title={t("title")} subtitle={t("subtitle")} gutter="none" />

      {renderWizardCard()}

      <div className="space-y-4">
        <ZoneHead title={t("howItWorks")} />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {HOW_IT_WORKS.map((step, i) => (
            <Card
              key={i}
              className="flex items-start gap-3 p-[var(--space-surface-compact)]"
            >
              <div className="w-8 h-8 rounded-lg bg-[var(--muted)] border border-[var(--border)] flex items-center justify-center shrink-0">
                {step.icon}
              </div>
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-2xs font-bold text-[var(--ink-muted)] uppercase tracking-wider">
                    {i + 1}
                  </span>
                  <p className="text-sm font-medium text-[var(--ink-primary)]">{t(step.titleKey)}</p>
                </div>
                <p className="text-xs text-[var(--ink-muted)] leading-relaxed">{t(step.descKey)}</p>
              </div>
            </Card>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <ZoneHead
          title={t("recentSearches")}
          sub={
            <Link href="/runs" className="hover:text-[var(--ink-secondary)] transition-colors">
              {t("viewAll")}
            </Link>
          }
        />

        {runsLoading && (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-[82px] rounded-lg" />
            ))}
          </div>
        )}

        {!runsLoading && recentRuns.length === 0 && (
          <EmptyState icon={History} title={t("noDiscoveryRunsYet")} />
        )}

        {!runsLoading && recentRuns.length > 0 && (
          <div className="flex flex-col gap-2">
            {recentRuns.map((run) => (
              <RunRow
                key={run.id}
                status={run.status}
                href={run.status === "succeeded" ? "/jobs" : `/runs/${run.id}`}
                typeLabel={t("discoveryRun")}
                statusLabel={tRuns(STATUS_KEY_MAP[run.status] ?? "statusQueued")}
                timeLabel={fmtTs(run.created_at)}
              />
            ))}
          </div>
        )}
      </div>

      <Row className="flex items-center gap-2">
        <Star size={13} className="text-[var(--ink-muted)] shrink-0" />
        <p className="text-xs text-[var(--ink-muted)]">
          {t("afterDiscoveryPrefix")}{" "}
          <Link href="/jobs" className="font-medium text-[var(--primary)] hover:underline">
            {t("roleInboxLink")}
          </Link>
          .
        </p>
      </Row>
    </PageContainer>
    </div>
  );
}
