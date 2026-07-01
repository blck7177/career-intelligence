import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { getJob, getLatestJobReport, getProfile, listFitReports, getFitReport } from "@/api/client";
import type { JobRead, JobReportResponse, FitReportResponse, JDStructured, ProfileRead } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { Badge } from "@/components/ui/badge";
import { fmtTs } from "@/lib/utils";
import { FavoriteButton } from "./FavoriteButton";
import { JobActions } from "./JobActions";
import { JobDetailTabs } from "./JobDetailTabs";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ job_id: string }>;
}

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

export default async function JobDetailPage({ params }: PageProps) {
  const { job_id } = await params;
  const token = await getServerToken();
  const t = await getTranslations("jobDetail");

  let job: JobRead;
  try {
    job = await getJob(job_id, token);
  } catch {
    notFound();
  }

  const [report, profile] = await Promise.all([
    getLatestJobReport(job_id, token).catch(() => null),
    getProfile(token).catch(() => null),
  ]);

  let fitReport: FitReportResponse | null = null;
  if (profile?.id) {
    const fitList = await listFitReports({ profile_id: profile.id }, token).catch(() => ({ items: [], total: 0 }));
    const match = fitList.items.find((fr) => fr.job_id === job_id);
    if (match) {
      fitReport = await getFitReport(match.id, token).catch(() => null);
    }
  }

  const jd = (job.jd_structured as JDStructured | null | undefined) ?? null;

  return (
    <>
      {/* Header — fixed at top */}
      <header
        className="shrink-0 bg-white px-7 py-3"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/" className="text-[13px] hover:underline shrink-0" style={{ color: "var(--primary)" }}>
              {t("backToInbox")}
            </Link>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-lg font-semibold leading-tight truncate" style={{ color: "oklch(16% 0.015 275)" }}>
                  {job.title}
                </h1>
                <Badge className={jobStatusBg(job.status) + " text-[11px] shrink-0"}>
                  {t(STATUS_KEY_MAP[job.status] ?? "invalid")}
                </Badge>
              </div>
              <div className="flex items-center gap-2.5 text-[13px] mt-1" style={{ color: "oklch(52% 0.01 275)" }}>
                <span className="font-medium" style={{ color: "oklch(36% 0.01 275)" }}>{job.company}</span>
                {job.location && <span>{job.location}</span>}
                <span style={{ color: "oklch(64% 0.01 275)" }}>{fmtTs(job.created_at.toString())}</span>
                <a
                  href={job.canonical_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  {t("viewPosting")}
                </a>
              </div>
            </div>
          </div>
          <FavoriteButton jobId={job_id} initialFavorited={!!job.is_favorited} />
        </div>
      </header>

      {/* Split panels — fill remaining height */}
      <JobDetailTabs
        job={job}
        jd={jd}
        jobReport={report}
        fitReport={fitReport}
        profile={profile}
        actions={
          <JobActions
            jobId={job_id}
            hasExistingReport={!!report}
            jobReportId={report?.id}
            hasProfile={!!profile}
          />
        }
      />
    </>
  );
}
