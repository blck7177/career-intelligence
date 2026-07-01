"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { batchArchiveJobs, batchAnalyzeJobs, importJob, getRun } from "@/api/client";
import { fmtTs } from "@/lib/utils";
import { ArchiveJobButton } from "./ArchiveJobButton";
import { FavoriteStarButton } from "./FavoriteStarButton";
import { JobFitCell } from "./JobFitCell";

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
  if (score >= 75) return "strong";
  if (score >= 50) return "good";
  return "partial";
}

export function JobListClient({ jobs, fitMap, hasProfile, profileId, favoritesOnly }: Props) {
  const t = useTranslations("jobs");
  const tCommon = useTranslations("common");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<Set<string>>(new Set());
  const [banner, setBanner] = useState<string | null>(null);
  const [pendingRunIds, setPendingRunIds] = useState<string[]>([]);
  const [showImportInput, setShowImportInput] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [unfavoritedIds, setUnfavoritedIds] = useState<Set<string>>(new Set());
  const getToken = useApiToken();
  const router = useRouter();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function matchBadge(style: MatchStyle): { text: string; classes: string } {
    if (style === "strong")
      return { text: t("matchStrong"), classes: "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]" };
    if (style === "good")
      return { text: t("matchGood"), classes: "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]" };
    if (style === "partial")
      return { text: t("matchPartial"), classes: "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]" };
    return { text: t("matchUnanalyzed"), classes: "bg-zinc-100 text-zinc-500" };
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

  function showBanner(msg: string) {
    setBanner(msg);
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
          <span>{banner}</span>
          <button onClick={() => setBanner(null)} className="text-[11px] opacity-60 hover:opacity-100">{t("dismiss")}</button>
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
            <button
              onClick={handleImportUrl}
              disabled={importing || !importUrl.trim()}
              className="h-9 px-4 rounded-lg text-sm font-medium text-white disabled:opacity-50"
              style={{ background: "var(--primary)" }}
            >
              {importing ? t("importing") : t("import")}
            </button>
            <button
              onClick={() => { setShowImportInput(false); setImportUrl(""); }}
              className="h-9 px-3 rounded-lg text-sm text-zinc-400 hover:text-zinc-600"
            >
              {tCommon("cancel")}
            </button>
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
          <label className="flex items-center gap-2 cursor-pointer text-[13px] text-zinc-500 hover:text-zinc-700">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="w-4 h-4 rounded border-zinc-300 accent-[var(--primary)]"
            />
            {t("selectAll")}
          </label>
          {selected.size > 0 && (
            <span className="text-[13px] text-zinc-400">
              {t("selectedCount", { count: selected.size })}
            </span>
          )}
        </div>
      )}

      {/* Job cards */}
      {visibleJobs.length === 0 && jobs.length > 0 && (
        <div className="rounded-xl border border-dashed py-10 text-center" style={{ borderColor: "var(--border)" }}>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>{t("noFavoritesLeft")}</p>
        </div>
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
              className="bg-white rounded-[10px] p-[20px_22px] transition-shadow hover:shadow-md"
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
                  className="w-4 h-4 rounded border-zinc-300 accent-[var(--primary)] shrink-0"
                />
                <span className={`py-[3px] px-2.5 rounded text-xs font-medium ${badge.classes}`}>
                  {badge.text}
                </span>
                {isDiscovered && (
                  <span className="py-[3px] px-2.5 rounded text-xs font-medium bg-zinc-100 text-zinc-500">
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
                  className="text-[17px] font-semibold mb-1 group-hover:underline"
                  style={{ color: isPartial ? "oklch(28% 0.012 275)" : "oklch(16% 0.015 275)" }}
                >
                  {job.title}
                </div>
                <div className="text-[13px] mb-3" style={{ color: "oklch(56% 0.01 275)" }}>
                  {job.company}
                  {job.location && ` · ${job.location}`}
                  {job.seniority_inferred && ` · ${job.seniority_inferred}`}
                </div>
              </Link>

              <div className="pt-3 flex items-center justify-between" style={{ borderTop: "1px solid oklch(93% 0.008 280)" }}>
                <div className="flex items-center gap-4">
                  <span className="text-[13px]" style={{ color: "oklch(58% 0.01 275)" }}>
                    {t("discovered", { time: fmtTs(job.created_at.toString()) })}
                  </span>
                  <ArchiveJobButton jobId={job.id} />
                </div>
                <Link
                  href={`/jobs/${job.id}`}
                  className="text-[13px] font-medium hover:underline"
                  style={{ color: isPartial ? "oklch(62% 0.01 275)" : "var(--primary)" }}
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
          <div className="w-px h-6 bg-zinc-200" />
          <button
            onClick={handleBatchArchive}
            disabled={!!loading}
            className="text-sm font-medium text-rose-600 bg-rose-50 hover:bg-rose-100 px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading === "archive" ? t("archiving") : t("archive")}
          </button>
          {hasProfile && (
            <button
              onClick={handleBatchAnalyze}
              disabled={!!loading}
              className="text-sm font-medium px-4 py-2 rounded-lg transition-all hover:shadow-sm disabled:opacity-50"
              style={{ color: "white", background: "var(--primary)" }}
            >
              {loading === "analyze" ? t("analyzing") : t("analyzeFit")}
            </button>
          )}
          <button
            onClick={() => setSelected(new Set())}
            className="text-sm text-zinc-400 hover:text-zinc-600 px-3 py-2"
          >
            {tCommon("cancel")}
          </button>
        </div>
      )}
    </>
  );
}
