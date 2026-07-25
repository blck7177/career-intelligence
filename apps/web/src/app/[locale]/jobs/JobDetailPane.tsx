"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { getJob, getLatestJobReport, getFitReport } from "@/api/client";
import type { JobRead, JobReportResponse, FitReportResponse, JDStructured, ProfileRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { fmtTs } from "@/lib/utils";
import { FavoriteButton } from "./[job_id]/FavoriteButton";
import { NotInterestedButton } from "./[job_id]/NotInterestedButton";
import { JobDetailTabs } from "./[job_id]/JobDetailTabs";

/* Status badge styling — mirrors the full-page /jobs/[id] header so the pane
   and the standalone page read identically. */
function jobStatusBg(status: string): string {
  if (status === "reportable") return "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]";
  if (status === "discovered") return "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]";
  if (status === "invalid") return "bg-rose-100 text-rose-800";
  return "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]";
}

const STATUS_KEY_MAP: Record<string, string> = {
  reportable: "reportable",
  discovered: "discovered",
  stale: "stale",
  invalid: "invalid",
  archived: "archived",
};

interface JobDetailPaneProps {
  jobId: string | null;
  profile: ProfileRead | null;
  /** Fit report id for this job from the parent list's fit map, if analyzed —
   *  lets us fetch the fit report directly instead of re-listing all of them. */
  fitReportId?: string | null;
}

interface Loaded {
  job: JobRead;
  report: JobReportResponse | null;
  fit: FitReportResponse | null;
}

export function JobDetailPane({ jobId, profile, fitReportId }: JobDetailPaneProps) {
  const t = useTranslations("jobDetail");
  const getToken = useApiToken();
  const [data, setData] = useState<Loaded | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  // Bumped by onMutated after a report/fit/resume action succeeds. Unlike
  // router.refresh() (which only re-runs Server Components), this is the only
  // way this component — which fetches its own data client-side — learns
  // that the job it's already showing just changed underneath it.
  const [refetchNonce, setRefetchNonce] = useState(0);

  useEffect(() => {
    if (!jobId) {
      setData(null);
      setLoading(false);
      setError(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const token = await getToken();
        const [job, report, fit] = await Promise.all([
          getJob(jobId, token),
          getLatestJobReport(jobId, token).catch(() => null),
          fitReportId ? getFitReport(fitReportId, token).catch(() => null) : Promise.resolve(null),
        ]);
        if (active) {
          setData({ job, report, fit });
          setLoading(false);
        }
      } catch {
        if (active) {
          setError(true);
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [jobId, fitReportId, getToken, refetchNonce]);

  if (!jobId) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <p className="text-sm text-center max-w-xs" style={{ color: "var(--ink-muted)" }}>
          {t("selectRole")}
        </p>
      </div>
    );
  }

  // Keep the previous job visible while the next one loads (no flash to
  // skeleton on every selection); only show the skeleton on the first load
  // when there's nothing to keep showing.
  if (loading && !data) {
    return <PaneSkeleton />;
  }

  if (error || !data) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
      </div>
    );
  }

  const { job, report, fit } = data;
  const jd = (job.jd_structured as JDStructured | null | undefined) ?? null;

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden" style={{ opacity: loading ? 0.6 : 1 }}>
      {/* Pane header — compact echo of the full-page header, minus the back
          link, plus an "open full page" affordance. */}
      <header className="shrink-0 bg-white px-6 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-base font-semibold leading-tight" style={{ color: "var(--ink-primary)" }}>
                {job.title}
              </h1>
              {job.status === "reportable" ? (
                <Tooltip content={t("reportableTooltip")}>
                  <Badge className={jobStatusBg(job.status) + " text-2xs shrink-0 cursor-help"}>
                    {t(STATUS_KEY_MAP[job.status] ?? "invalid")}
                  </Badge>
                </Tooltip>
              ) : (
                <Badge className={jobStatusBg(job.status) + " text-2xs shrink-0"}>
                  {t(STATUS_KEY_MAP[job.status] ?? "invalid")}
                </Badge>
              )}
              {job.jd_source === "research_mirror" && (
                <Badge className="bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)] text-2xs shrink-0">
                  {t("jdFromMirror")}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2.5 text-sm mt-[var(--space-stack-xs)]" style={{ color: "var(--ink-muted)" }}>
              <span className="font-medium" style={{ color: "var(--ink-secondary)" }}>{job.company}</span>
              {job.location && <span>{job.location}</span>}
              <span style={{ color: "var(--ink-faint)" }}>
                {job.posted_at ? t("postedOn", { date: fmtTs(job.posted_at) }) : fmtTs(job.created_at.toString())}
              </span>
              {job.canonical_url.startsWith("http") && (
                <a
                  href={job.canonical_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  {t("viewPosting")}
                </a>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <Link
              href={`/jobs/${job.id}`}
              className="flex items-center gap-1 text-sm font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              {t("openFull")}
              <ExternalLink size={13} />
            </Link>
            <FavoriteButton jobId={job.id} initialFavorited={!!job.is_favorited} />
            <NotInterestedButton jobId={job.id} initialNotInterested={!!job.is_not_interested} />
          </div>
        </div>
      </header>

      {/* key on job id: remount the tabs on job change so tab state and scroll
          position reset to the top for each newly selected role. */}
      <JobDetailTabs
        key={job.id}
        job={job}
        jd={jd}
        jobReport={report}
        fitReport={fit}
        profile={profile}
        hasExistingReport={!!report}
        jobReportId={report?.id}
        onMutated={() => setRefetchNonce((n) => n + 1)}
      />
    </div>
  );
}

function PaneSkeleton() {
  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden animate-pulse">
      <div className="shrink-0 px-6 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="h-5 w-2/3 rounded bg-[var(--muted)]" />
        <div className="h-3.5 w-1/2 rounded bg-[var(--muted)] mt-2.5" />
      </div>
      <div className="px-6 pt-4">
        <div className="flex gap-4">
          <div className="h-6 w-28 rounded bg-[var(--muted)]" />
          <div className="h-6 w-20 rounded bg-[var(--muted)]" />
          <div className="h-6 w-24 rounded bg-[var(--muted)]" />
        </div>
      </div>
      <div className="p-[var(--space-surface-spacious)] space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-4 rounded bg-[var(--muted)]" style={{ width: `${90 - i * 8}%` }} />
        ))}
      </div>
    </div>
  );
}
