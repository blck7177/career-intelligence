"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check, Plus, Star, ThumbsDown } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { batchArchiveJobs, batchAnalyzeJobs, importJob, getRun } from "@/api/client";
import type { ProfileRead } from "@/api/client";
import { bandOf, BAND } from "@/lib/matchBand";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { FavoriteStarButton } from "./FavoriteStarButton";
import { NotInterestedIconButton } from "./NotInterestedIconButton";
import { JobFilters } from "./JobFilters";
import { JobDetailPane } from "./JobDetailPane";

interface JobItem {
  id: string;
  title: string;
  company: string;
  location?: string | null;
  status: string;
  seniority_inferred?: string | null;
  created_at: string;
  latest_job_report_id?: string | null;
  is_favorited?: boolean;
  is_not_interested?: boolean;
  is_applied?: boolean;
}

interface FitData {
  id: string;
  score: number;
  recommended_next_action?: string | null;
}

interface ProfileOption {
  id: string;
  label: string;
}

interface Props {
  /** Current page's rows only (server-paginated) — NOT the full filtered set. */
  jobs: JobItem[];
  fitMap: Record<string, FitData>;
  profile: ProfileRead | null;
  profileId: string | null;
  profiles: ProfileOption[];
  roleCategories: string[];
  companies: string[];
  favoritesOnly: boolean;
  notInterestedOnly: boolean;
  statusFilter: string;
  /** Filtered total across all pages — what the header count shows. */
  totalCount: number;
  currentPage: number;
  totalPages: number;
}

type StatusFilter = "all" | "discovered" | "reportable" | "stale" | "invalid";

const SAVED_VIEWS: { key: string; status: StatusFilter }[] = [
  { key: "viewAll", status: "all" },
  { key: "reportReady", status: "reportable" },
  { key: "needsReport", status: "discovered" },
  { key: "stale", status: "stale" },
];

const LG = "(min-width: 1024px)";

function pageNumbers(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set([1, 2, total - 1, total, current - 1, current, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | "ellipsis")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) result.push("ellipsis");
    result.push(p);
    prev = p;
  }
  return result;
}

export function JobsMasterDetail({
  jobs,
  fitMap,
  profile,
  profileId,
  profiles,
  roleCategories,
  companies,
  favoritesOnly,
  notInterestedOnly,
  statusFilter,
  totalCount,
  currentPage,
  totalPages,
}: Props) {
  const t = useTranslations("jobs");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const getToken = useApiToken();
  const isDesktop = useMediaQuery(LG);
  const hasProfile = !!profileId;

  // ── Batch selection / actions (ported from the old card list) ──
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<Set<string>>(new Set());
  const [banner, setBanner] = useState<{ message: string; jobId?: string } | null>(null);
  const [pendingRunIds, setPendingRunIds] = useState<string[]>([]);
  const [showImportInput, setShowImportInput] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [unfavoritedIds, setUnfavoritedIds] = useState<Set<string>>(new Set());
  const [reInterestedIds, setReInterestedIds] = useState<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // In the favorites-only / not-interested-only view, toggling a card's own
  // filter facet off drops it from view at once instead of waiting for the
  // next full navigation.
  useEffect(() => {
    setUnfavoritedIds(new Set());
    setReInterestedIds(new Set());
  }, [jobs]);
  const visibleJobs = favoritesOnly
    ? jobs.filter((j) => !unfavoritedIds.has(j.id))
    : notInterestedOnly
      ? jobs.filter((j) => !reInterestedIds.has(j.id))
      : jobs;

  // ── Selection (viewed row) ──
  // Local state is the source of truth for which row the pane shows (so the
  // pane always re-renders on selection); the ?selected= URL param is kept in
  // sync via the History API purely for shareability + back/forward. This
  // deliberately does NOT depend on pushState re-flowing into useSearchParams.
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("selected"));
  const selectedValid =
    selectedId && visibleJobs.some((j) => j.id === selectedId) ? selectedId : null;
  // Show the first row immediately on desktop even before the effect syncs, so
  // the pane never flashes the "select a role" placeholder on load.
  const selectedForPane = selectedValid ?? (isDesktop ? visibleJobs[0]?.id ?? null : null);

  // Auto-select the first row on desktop when nothing valid is selected
  // (initial load, or after a filter change invalidated the old selection).
  useEffect(() => {
    if (!isDesktop || selectedValid) return;
    const first = visibleJobs[0]?.id ?? null;
    setSelectedId(first);
    const params = new URLSearchParams(window.location.search);
    if (first) params.set("selected", first);
    else params.delete("selected");
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }, [isDesktop, selectedValid, visibleJobs]);

  // Restore selection on browser back/forward.
  useEffect(() => {
    const onPop = () => setSelectedId(new URLSearchParams(window.location.search).get("selected"));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const selectJob = useCallback((id: string) => {
    setSelectedId(id);
    const params = new URLSearchParams(window.location.search);
    params.set("selected", id);
    window.history.pushState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, []);

  const openRow = useCallback(
    (id: string) => {
      if (isDesktop) selectJob(id);
      else router.push(`/jobs/${id}`);
    },
    [isDesktop, selectJob, router],
  );

  // ── Batch action plumbing ──
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (pendingRunIds.length === 0) return;
    const remaining = new Set(pendingRunIds);
    pollRef.current = setInterval(async () => {
      try {
        const token = await getToken();
        for (const runId of [...remaining]) {
          try {
            const run = await getRun(runId, token);
            if (run.status !== "queued" && run.status !== "running") remaining.delete(runId);
          } catch {
            remaining.delete(runId);
          }
        }
        if (remaining.size === 0) {
          stopPolling();
          setPendingRunIds([]);
          setAnalyzing(new Set());
          showBanner(t("fitAnalysisComplete"));
          router.refresh();
        }
      } catch {
        // ignore transient errors
      }
    }, 5000);
    return stopPolling;
  }, [pendingRunIds, getToken, router, stopPolling, t]);

  function showBanner(msg: string, jobId?: string) {
    setBanner({ message: msg, jobId });
    setTimeout(() => setBanner(null), 6000);
  }

  function toggleCheck(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allChecked = visibleJobs.length > 0 && checked.size === visibleJobs.length;
  function toggleAll() {
    setChecked(allChecked ? new Set() : new Set(visibleJobs.map((j) => j.id)));
  }

  function handleFavoriteToggled(jobId: string, favorited: boolean) {
    if (favorited || !favoritesOnly) return;
    setUnfavoritedIds((prev) => new Set(prev).add(jobId));
    setChecked((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });
  }

  function handleNotInterestedToggled(jobId: string, notInterested: boolean) {
    if (notInterested || !notInterestedOnly) return;
    setReInterestedIds((prev) => new Set(prev).add(jobId));
    setChecked((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });
  }

  async function handleImportUrl() {
    const url = importUrl.trim();
    if (!url) return;
    setImporting(true);
    try {
      const token = await getToken();
      const result = await importJob({ url }, token);
      const jd = result.jd_fetched ? t("jdFetched") : t("noJdSuffix");
      showBanner(
        t(result.created ? "importedMsg" : "existsMsg", {
          title: result.job.title,
          company: result.job.company,
          jd,
        }),
        result.job.id,
      );
      setImportUrl("");
      setShowImportInput(false);
      router.refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Import failed";
      showBanner(t("importFailedMsg", { msg }));
    } finally {
      setImporting(false);
    }
  }

  async function handleBatchArchive() {
    setLoading("archive");
    try {
      const token = await getToken();
      const result = await batchArchiveJobs([...checked], token);
      showBanner(t("archivedMsg", { count: result.archived_count }));
      setChecked(new Set());
      router.refresh();
    } finally {
      setLoading(null);
    }
  }

  async function handleBatchAnalyze() {
    setLoading("analyze");
    try {
      const token = await getToken();
      const submitted = [...checked].filter(
        (id) => jobs.find((j) => j.id === id)?.status !== "discovered",
      );
      if (submitted.length === 0) {
        showBanner(t("allMissingJD"));
        setLoading(null);
        return;
      }
      const result = await batchAnalyzeJobs(submitted, profileId, token);
      const fitDirect = result.run_ids.length - (result.report_first?.length ?? 0);
      const reportFirst = result.report_first?.length ?? 0;
      const skipped = result.skipped.length;
      const parts: string[] = [];
      if (fitDirect > 0) parts.push(t("fitReportsQueued", { count: fitDirect }));
      if (reportFirst > 0) parts.push(t("reportFirstQueued", { count: reportFirst }));
      if (skipped > 0) parts.push(t("skippedCount", { count: skipped }));
      showBanner(parts.join(" · "));
      setAnalyzing(new Set(submitted.filter((id) => !result.skipped.includes(id))));
      setChecked(new Set());
      if (result.run_ids.length > 0) setPendingRunIds(result.run_ids);
    } finally {
      setLoading(null);
    }
  }

  function pageHref(p: number): string {
    const params = new URLSearchParams(searchParams.toString());
    if (p <= 1) params.delete("page");
    else params.set("page", String(p));
    params.delete("selected");
    const s = params.toString();
    return s ? `/jobs?${s}` : "/jobs";
  }

  function viewHref(status: StatusFilter): string {
    const params = new URLSearchParams(searchParams.toString());
    if (status === "all") params.delete("status");
    else params.set("status", status);
    params.delete("page");
    params.delete("selected");
    const s = params.toString();
    return s ? `/jobs?${s}` : "/jobs";
  }

  function favoritesHref(): string {
    const params = new URLSearchParams(searchParams.toString());
    if (favoritesOnly) params.delete("favorites");
    else params.set("favorites", "1");
    params.delete("page");
    params.delete("selected");
    const s = params.toString();
    return s ? `/jobs?${s}` : "/jobs";
  }

  function notInterestedHref(): string {
    const params = new URLSearchParams(searchParams.toString());
    if (notInterestedOnly) params.delete("not_interested");
    else params.set("not_interested", "1");
    params.delete("page");
    params.delete("selected");
    const s = params.toString();
    return s ? `/jobs?${s}` : "/jobs";
  }

  return (
    <div className="flex-1 min-h-0 flex">
      {/* ── Left: dense list column ── */}
      <div className="flex flex-col w-full lg:w-[360px] xl:w-[400px] lg:shrink-0 min-h-0 lg:border-r border-[var(--border)]">
        {/* Slim header: title + count · import · status views · filters */}
        <div className="shrink-0 px-[var(--space-row-edge)] pt-4 pb-3 space-y-3" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-base font-semibold flex items-baseline gap-2" style={{ color: "var(--ink-primary)" }}>
              {t("title")}
              <span className="text-xs font-normal" style={{ color: "var(--ink-muted)" }}>
                {t("roleCount", { count: totalCount })}
              </span>
            </h1>
            {!showImportInput && (
              <button
                onClick={() => setShowImportInput(true)}
                className="flex items-center gap-1 text-sm font-medium hover:opacity-80 shrink-0"
                style={{ color: "var(--primary)" }}
              >
                <Plus size={14} />
                {t("importByUrl")}
              </button>
            )}
          </div>

          {showImportInput && (
            <div className="flex items-center gap-2">
              <input
                type="url"
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleImportUrl()}
                placeholder={t("importPlaceholder")}
                autoFocus
                className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
                style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
              />
              <Button onClick={handleImportUrl} disabled={!importUrl.trim()} loading={importing} size="sm">
                {t("import")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => { setShowImportInput(false); setImportUrl(""); }}>
                {tCommon("cancel")}
              </Button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5">
            {SAVED_VIEWS.map(({ key, status }) => (
              <Link
                key={status}
                href={viewHref(status)}
                className={optionPillVariants({ selected: statusFilter === status, className: "!h-7 !px-2.5 !text-xs" })}
              >
                {t(key)}
              </Link>
            ))}
            <div className="w-px self-stretch bg-[var(--border)] mx-0.5" />
            <Link
              href={favoritesHref()}
              className={optionPillVariants({ selected: favoritesOnly, className: "!h-7 !px-2.5 !text-xs gap-1" })}
            >
              <Star size={11} fill={favoritesOnly ? "currentColor" : "none"} />
              {t("favorites")}
            </Link>
            <Link
              href={notInterestedHref()}
              className={optionPillVariants({ selected: notInterestedOnly, className: "!h-7 !px-2.5 !text-xs gap-1" })}
            >
              <ThumbsDown size={11} fill={notInterestedOnly ? "currentColor" : "none"} />
              {t("notInterested")}
            </Link>
          </div>

          <JobFilters profiles={profiles} roleCategories={roleCategories} companies={companies} />
        </div>

        {/* Result banner */}
        {banner && (
          <div
            className="shrink-0 flex items-center justify-between gap-3 px-[var(--space-row-edge)] py-2 text-sm font-medium"
            style={{ background: "oklch(96% 0.015 145)", color: "oklch(30% 0.08 145)", borderBottom: "1px solid oklch(88% 0.04 145)" }}
          >
            <span className="flex items-center gap-2 min-w-0">
              <span className="truncate">{banner.message}</span>
              {banner.jobId && (
                <button onClick={() => openRow(banner.jobId!)} className="font-semibold hover:underline shrink-0">
                  {tCommon("viewRole")}
                </button>
              )}
            </span>
            <button onClick={() => setBanner(null)} className="text-2xs opacity-60 hover:opacity-100 shrink-0">{t("dismiss")}</button>
          </div>
        )}

        {/* Select-all utility row */}
        {visibleJobs.length > 0 && (
          <div className="shrink-0 flex items-center gap-2 px-[var(--space-row-edge)] py-1.5 border-b border-[var(--border)]">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">
              <input
                type="checkbox"
                checked={allChecked}
                onChange={toggleAll}
                className="w-3.5 h-3.5 rounded border-[var(--border)] accent-[var(--primary)]"
              />
              {t("selectAll")}
            </label>
            {checked.size > 0 && (
              <span className="text-xs text-[var(--ink-muted)]">{t("selectedCount", { count: checked.size })}</span>
            )}
          </div>
        )}

        {/* Rows — paginated 20/page (this component only ever receives one
            page's worth of jobs; page.tsx does the slicing server-side). */}
        {visibleJobs.length === 0 ? (
          <div className="flex-1 min-h-0 flex items-center justify-center p-6">
            <EmptyState
              icon={notInterestedOnly ? ThumbsDown : Star}
              title={
                favoritesOnly
                  ? t("noFavoritesLeft")
                  : notInterestedOnly
                    ? t("noNotInterestedLeft")
                    : t("emptyTitle")
              }
            />
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto">
            {visibleJobs.map((job) => {
              const fit = fitMap[job.id];
              const isViewed = isDesktop && selectedForPane === job.id;
              const isChecked = checked.has(job.id);
              const isDiscovered = job.status === "discovered";
              return (
                <JobRow
                  key={job.id}
                  job={job}
                  score={fit?.score}
                  isViewed={isViewed}
                  isChecked={isChecked}
                  isDiscovered={isDiscovered}
                  isAnalyzing={analyzing.has(job.id)}
                  noJdLabel={t("noJD")}
                  analyzingLabel={t("analyzing")}
                  appliedLabel={t("appliedMark")}
                  onOpen={() => openRow(job.id)}
                  onToggleCheck={() => toggleCheck(job.id)}
                  onFavoriteToggled={(fav) => handleFavoriteToggled(job.id, fav)}
                  onNotInterestedToggled={(ni) => handleNotInterestedToggled(job.id, ni)}
                />
              );
            })}
          </div>
        )}

        {/* Pager */}
        {totalPages > 1 && (
          <div className="shrink-0 flex items-center justify-center gap-1 px-2 py-2.5" style={{ borderTop: "1px solid var(--border)" }}>
            <Link
              href={pageHref(currentPage - 1)}
              aria-disabled={currentPage === 1}
              className="h-7 px-2 rounded-md text-xs font-medium flex items-center"
              style={
                currentPage === 1
                  ? { color: "var(--muted-foreground)", pointerEvents: "none", opacity: 0.4 }
                  : { color: "var(--foreground)", border: "1px solid var(--border)" }
              }
            >
              {t("prev")}
            </Link>
            {pageNumbers(currentPage, totalPages).map((p, idx) =>
              p === "ellipsis" ? (
                <span key={`e${idx}`} className="px-1 text-xs" style={{ color: "var(--muted-foreground)" }}>
                  …
                </span>
              ) : (
                <Link
                  key={p}
                  href={pageHref(p)}
                  className="h-7 w-7 rounded-md text-xs font-medium flex items-center justify-center tabular-nums"
                  style={
                    p === currentPage
                      ? { background: "var(--ink-primary)", color: "#fff" }
                      : { color: "var(--foreground)", border: "1px solid var(--border)" }
                  }
                >
                  {p}
                </Link>
              ),
            )}
            <Link
              href={pageHref(currentPage + 1)}
              aria-disabled={currentPage === totalPages}
              className="h-7 px-2 rounded-md text-xs font-medium flex items-center"
              style={
                currentPage === totalPages
                  ? { color: "var(--muted-foreground)", pointerEvents: "none", opacity: 0.4 }
                  : { color: "var(--foreground)", border: "1px solid var(--border)" }
              }
            >
              {t("next")}
            </Link>
          </div>
        )}
      </div>

      {/* ── Right: detail pane (desktop only) ── */}
      <div className="hidden lg:flex flex-1 min-w-0 min-h-0">
        <JobDetailPane
          jobId={selectedForPane}
          profile={profile}
          fitReportId={selectedForPane ? fitMap[selectedForPane]?.id ?? null : null}
        />
      </div>

      {/* ── Batch action bar ── */}
      {checked.size > 0 && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2.5 bg-white rounded-2xl shadow-xl px-5 py-3.5 z-50"
          style={{ border: "1px solid var(--border)" }}
        >
          <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {t("selectedCount", { count: checked.size })}
          </span>
          <div className="w-px h-6 bg-[var(--border)]" />
          <Button
            onClick={handleBatchArchive}
            disabled={!!loading}
            loading={loading === "archive"}
            size="sm"
            variant="ghost"
            className="text-rose-600 bg-rose-50 hover:bg-rose-100"
          >
            {t("archive")}
          </Button>
          {hasProfile && (
            <Button onClick={handleBatchAnalyze} disabled={!!loading} loading={loading === "analyze"} size="sm">
              {t("analyzeFit")}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => setChecked(new Set())}>
            {tCommon("cancel")}
          </Button>
        </div>
      )}
    </div>
  );
}

/* ── Dense list row ── */

interface JobRowProps {
  job: JobItem;
  score?: number;
  isViewed: boolean;
  isChecked: boolean;
  isDiscovered: boolean;
  isAnalyzing: boolean;
  noJdLabel: string;
  analyzingLabel: string;
  appliedLabel: string;
  onOpen: () => void;
  onToggleCheck: () => void;
  onFavoriteToggled: (favorited: boolean) => void;
  onNotInterestedToggled: (notInterested: boolean) => void;
}

/** Same gold used for the favorited-star fill (FavoriteStarButton) — reused
 * here for the company/location separator dot instead of introducing a new
 * accent color. */
const DOT_COLOR = "oklch(60% 0.15 80)";

function JobRow({
  job,
  score,
  isViewed,
  isChecked,
  isDiscovered,
  isAnalyzing,
  noJdLabel,
  analyzingLabel,
  appliedLabel,
  onOpen,
  onToggleCheck,
  onFavoriteToggled,
  onNotInterestedToggled,
}: JobRowProps) {
  const band = score !== undefined ? BAND[bandOf(score)] : null;
  // Mirrors job.is_favorited/is_not_interested locally so a just-toggled
  // row's icon stays visible without a hover, instead of only ever tracking
  // the server prop (which won't reflect the toggle until the next full
  // refresh).
  const [favorited, setFavorited] = useState(!!job.is_favorited);
  const [notInterested, setNotInterested] = useState(!!job.is_not_interested);
  const starVisible = favorited || isViewed;
  const thumbVisible = notInterested || isViewed;

  return (
    // Container + a real button on the title, not role="button" on the row: the
    // row used to own Enter/Space, and keydown bubbles, so pressing space on
    // the checkbox below reached the row's preventDefault() — which cancels the
    // checkbox's own default action. Keyboard users could not tick a row, and
    // the attempt opened the job instead. (Found by the guard test written for
    // the same bug in the Applications list; the mouse path was always fine,
    // which is why it survived.)
    <div
      onClick={onOpen}
      className="group flex items-center gap-2.5 px-[var(--space-row-edge)] py-2.5 cursor-pointer transition-colors border-l-2 border-b"
      style={{
        borderLeftColor: isViewed ? "var(--primary)" : "transparent",
        borderBottomColor: "var(--border)",
        background: isViewed ? "var(--secondary)" : "transparent",
        opacity: isDiscovered ? 0.7 : 1,
      }}
    >
      <span onClick={(e) => e.stopPropagation()} className="shrink-0 flex items-center">
        <input
          type="checkbox"
          checked={isChecked}
          onChange={onToggleCheck}
          aria-label="select"
          className="w-3.5 h-3.5 rounded border-[var(--border)] accent-[var(--primary)]"
        />
      </span>

      <button type="button" className="flex-1 min-w-0 text-left">
        <span className="flex items-center gap-1.5">
          <span
            className="text-sm font-medium truncate group-hover:underline"
            style={{ color: isDiscovered ? "var(--ink-secondary)" : "var(--ink-primary)" }}
          >
            {job.title}
          </span>
          {isDiscovered && (
            <span className="shrink-0 px-1.5 py-0.5 rounded text-2xs font-medium bg-[var(--muted)] text-[var(--ink-muted)]">
              {noJdLabel}
            </span>
          )}
          {job.is_applied && (
            <span
              className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-2xs font-semibold"
              style={{ background: "var(--match-good-bg)", color: "var(--match-good-fg)" }}
            >
              <Check size={10} strokeWidth={3} />
              {appliedLabel}
            </span>
          )}
        </span>
        <span className="block text-xs truncate mt-0.5" style={{ color: "var(--ink-muted)" }}>
          {job.company}
          {job.location && (
            <>
              <span style={{ color: DOT_COLOR }}> · </span>
              {job.location}
            </>
          )}
        </span>
      </button>

      <div className="shrink-0 flex items-center gap-2">
        {isAnalyzing ? (
          <span className="flex items-center gap-1 text-2xs font-medium" style={{ color: "var(--primary)" }}>
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
              <path d="M12 2a10 10 0 019.95 9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
            {analyzingLabel}
          </span>
        ) : band ? (
          <span className="px-1.5 py-0.5 rounded text-2xs font-semibold tabular-nums" style={{ background: band.bg, color: band.fg }}>
            {score}%
          </span>
        ) : (
          <span className="text-2xs" style={{ color: "var(--ink-faint)" }}>—</span>
        )}
        <span
          onClick={(e) => e.stopPropagation()}
          className={`flex items-center transition-opacity ${starVisible ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"}`}
        >
          <FavoriteStarButton
            jobId={job.id}
            initialFavorited={!!job.is_favorited}
            onToggled={(fav) => {
              setFavorited(fav);
              onFavoriteToggled(fav);
            }}
          />
        </span>
        <span
          onClick={(e) => e.stopPropagation()}
          className={`flex items-center transition-opacity ${thumbVisible ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"}`}
        >
          <NotInterestedIconButton
            jobId={job.id}
            initialNotInterested={!!job.is_not_interested}
            onToggled={(ni) => {
              setNotInterested(ni);
              onNotInterestedToggled(ni);
            }}
          />
        </span>
      </div>
    </div>
  );
}
