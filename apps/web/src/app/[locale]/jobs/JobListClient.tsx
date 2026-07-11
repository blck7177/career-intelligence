"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Star } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { batchArchiveJobs, batchAnalyzeJobs, importJob, getRun } from "@/api/client";
import { fmtTs } from "@/lib/utils";
import { ArchiveJobButton } from "./ArchiveJobButton";
import { FavoriteStarButton } from "./FavoriteStarButton";
import { JobFitCell } from "./JobFitCell";
import { bandOf, BAND } from "@/lib/matchBand";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";

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
}

interface FitData {
  id: string;
  score: number;
  recommended_next_action?: string | null;
}

interface Props {
  jobs: JobItem[];
  fitMap: Record<string, FitData>;
  hasProfile: boolean;
  profileId?: string | null;
  favoritesOnly?: boolean;
}

type MatchStyle = "strong" | "good" | "partial" | "unanalyzed";

function matchStyle(score: number | undefined): MatchStyle {
  if (score === undefined) return "unanalyzed";
  if (score >= 70) return "strong";
  if (score >= 50) return "good";
  return "partial";
}

export function JobListClient({ jobs, fitMap, hasProfile, profileId, favoritesOnly }: Props) {
  const t = useTranslations("jobs");
  const tCommon = useTranslations("common");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<Set<string>>(new Set());
  const [banner, setBanner] = useState<{ message: string; jobId?: string } | null>(null);
  const [pendingRunIds, setPendingRunIds] = useState<string[]>([]);
  const [showImportInput, setShowImportInput] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [unfavoritedIds, setUnfavoritedIds] = useState<Set<string>>(new Set());
  const getToken = useApiToken();
  const router = useRouter();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function matchBadge(style: MatchStyle): { text: string; bg: string; fg: string } {
    if (style === "strong") return { text: t("matchStrong"), bg: BAND.strong.bg, fg: BAND.strong.fg };
    if (style === "good") return { text: t("matchGood"), bg: BAND.partial.bg, fg: BAND.partial.fg };
    if (style === "partial") return { text: t("matchPartial"), bg: BAND.gaps.bg, fg: BAND.gaps.fg };
    return { text: t("matchUnanalyzed"), bg: "", fg: "" };
  }

  // Reset whenever the server gives us a fresh job list (new page/filter).
  useEffect(() => {
    setUnfavoritedIds(new Set());
  }, [jobs]);

  // In the favorites-only view, unfavoriting a card removes it from view immediately.
  const visibleJobs = favoritesOnly ? jobs.filter((j) => !unfavoritedIds.has(j.id)) : jobs;

  function handleFavoriteToggled(jobId: string, favorited: boolean) {
    if (favorited || !favoritesOnly) return;
    setUnfavoritedIds((prev) => new Set(prev).add(jobId));
    setSelected((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });
  }

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
            if (run.status !== "queued" && run.status !== "running") {
              remaining.delete(runId);
            }
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

  const allSelected = visibleJobs.length > 0 && selected.size === visibleJobs.length;

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleJobs.map((j) => j.id)));
    }
  }

  function showBanner(msg: string, jobId?: string) {
    setBanner({ message: msg, jobId });
    setTimeout(() => setBanner(null), 6000);
  }

  async function handleImportUrl() {
    const url = importUrl.trim();
    if (!url) return;
    setImporting(true);
    try {
      const token = await getToken();
      const result = await importJob(url, token);
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
      const result = await batchArchiveJobs([...selected], token);
      showBanner(t("archivedMsg", { count: result.archived_count }));
      setSelected(new Set());
      router.refresh();
    } finally {
      setLoading(null);
    }
  }

  async function handleBatchAnalyze() {
    setLoading("analyze");
    try {
      const token = await getToken();
      const submitted = [...selected].filter(
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

      const analyzingIds = new Set(
        submitted.filter((id) => !result.skipped.includes(id)),
      );
      setAnalyzing(analyzingIds);
      setSelected(new Set());
      if (result.run_ids.length > 0) {
        setPendingRunIds(result.run_ids);
      }
    } finally {
      setLoading(null);
    }
  }

  return (
    <>
      {/* Result banner */}
      {banner && (
        <div
          className="flex items-center justify-between gap-3 mb-3 px-4 py-2.5 rounded-lg text-sm font-medium"
          style={{ background: "oklch(96% 0.015 145)", color: "oklch(30% 0.08 145)", border: "1px solid oklch(88% 0.04 145)" }}
        >
          <span className="flex items-center gap-2">
            {banner.message}
            {banner.jobId && (
              <Link href={`/jobs/${banner.jobId}`} className="font-semibold hover:underline">
                {tCommon("viewRole")}
              </Link>
            )}
          </span>
          <button onClick={() => setBanner(null)} className="text-2xs opacity-60 hover:opacity-100">{t("dismiss")}</button>
        </div>
      )}

      {/* Import job by URL */}
      <div className="mb-3">
        {showImportInput ? (
          <div className="flex items-center gap-2">
            <input
              type="url"
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleImportUrl()}
              placeholder={t("importPlaceholder")}
              autoFocus
              className="flex-1 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
              style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            />
            <Button onClick={handleImportUrl} disabled={!importUrl.trim()} loading={importing} size="sm">
              {t("import")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setShowImportInput(false); setImportUrl(""); }}
            >
              {tCommon("cancel")}
            </Button>
          </div>
        ) : (
          <button
            onClick={() => setShowImportInput(true)}
            className="flex items-center gap-1.5 text-sm font-medium hover:opacity-80"
            style={{ color: "var(--primary)" }}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M8 1v14M1 8h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            {t("importByUrl")}
          </button>
        )}
      </div>

      {/* Select all toggle */}
      {visibleJobs.length > 0 && (
        <div className="flex items-center gap-2 mb-2">
          <label className="flex items-center gap-2 cursor-pointer text-sm text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="w-4 h-4 rounded border-[var(--border)] accent-[var(--primary)]"
            />
            {t("selectAll")}
          </label>
          {selected.size > 0 && (
            <span className="text-sm text-[var(--ink-muted)]">
              {t("selectedCount", { count: selected.size })}
            </span>
          )}
        </div>
      )}

      {/* Job cards */}
      {visibleJobs.length === 0 && jobs.length > 0 && (
        <EmptyState icon={Star} title={t("noFavoritesLeft")} />
      )}
      <div className="flex flex-col gap-2.5">
        {visibleJobs.map((job) => {
          const fr = fitMap[job.id];
          const score = fr?.score;
          const ms = matchStyle(score);
          const badge = matchBadge(ms);
          const isDiscovered = job.status === "discovered";
          const isPartial = ms === "partial" || ms === "unanalyzed" || isDiscovered;
          const isSelected = selected.has(job.id);

          return (
            <div
              key={job.id}
              className="bg-white rounded-[10px] p-[var(--space-row-card-y)_var(--space-row-card-x)] transition-shadow hover:shadow-md"
              style={{
                border: isSelected
                  ? "2px solid var(--primary)"
                  : "1px solid var(--border)",
                boxShadow: "0 1px 3px oklch(0% 0 0 / 0.04)",
                opacity: isDiscovered ? 0.6 : isPartial ? 0.88 : 1,
              }}
            >
              <div className="flex items-center gap-2.5 mb-3">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleOne(job.id)}
                  className="w-4 h-4 rounded border-[var(--border)] accent-[var(--primary)] shrink-0"
                />
                <span
                  className={`py-[3px] px-2.5 rounded text-xs font-medium ${ms === "unanalyzed" ? "bg-[var(--muted)] text-[var(--ink-muted)]" : ""}`}
                  style={ms === "unanalyzed" ? undefined : { backgroundColor: badge.bg, color: badge.fg }}
                >
                  {badge.text}
                </span>
                {isDiscovered && (
                  <span className="py-[3px] px-2.5 rounded text-xs font-medium bg-[var(--muted)] text-[var(--ink-muted)]">
                    {t("noJD")}
                  </span>
                )}
                <div className="flex-1" />
                <div className="flex items-center gap-3 shrink-0">
                  {analyzing.has(job.id) ? (
                    <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--primary)" }}>
                      <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
                        <path d="M12 2a10 10 0 019.95 9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                      </svg>
                      {t("analyzing")}
                    </span>
                  ) : (
                    <JobFitCell
                      jobId={job.id}
                      jobReportId={job.latest_job_report_id}
                      hasProfile={hasProfile}
                      fitReport={fr ? { id: fr.id, score: fr.score, recommended_next_action: fr.recommended_next_action } : undefined}
                    />
                  )}
                  <FavoriteStarButton
                    jobId={job.id}
                    initialFavorited={!!job.is_favorited}
                    onToggled={(favorited) => handleFavoriteToggled(job.id, favorited)}
                  />
                </div>
              </div>

              <Link href={`/jobs/${job.id}`} className="block group">
                <div
                  className="text-lg font-semibold mb-1 group-hover:underline"
                  style={{ color: isPartial ? "var(--ink-secondary)" : "var(--ink-primary)" }}
                >
                  {job.title}
                </div>
                <div className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>
                  {job.company}
                  {job.location && ` · ${job.location}`}
                  {job.seniority_inferred && ` · ${job.seniority_inferred}`}
                </div>
              </Link>

              <div className="pt-3 flex items-center justify-between" style={{ borderTop: "1px solid var(--border)" }}>
                <div className="flex items-center gap-4">
                  <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
                    {t("discovered", { time: fmtTs(job.created_at.toString()) })}
                  </span>
                  <ArchiveJobButton jobId={job.id} />
                </div>
                <Link
                  href={`/jobs/${job.id}`}
                  className="text-sm font-medium hover:underline"
                  style={{ color: isPartial ? "var(--ink-faint)" : "var(--primary)" }}
                >
                  {tCommon("viewRole")}
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      {/* Batch action bar */}
      {selected.size > 0 && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2.5 bg-white rounded-2xl shadow-xl px-5 py-3.5 z-50"
          style={{ border: "1px solid var(--border)" }}
        >
          <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {t("selectedCount", { count: selected.size })}
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
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            {tCommon("cancel")}
          </Button>
        </div>
      )}
    </>
  );
}
