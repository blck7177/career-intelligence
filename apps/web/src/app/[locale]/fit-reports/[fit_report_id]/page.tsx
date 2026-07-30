import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { getFitReport, getJob, getProfile } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { FitReportTabs } from "@/components/FitReportTabs";
import { PageContainer } from "@/components/ui/page-container";
import { DetailBackBar } from "@/components/ui/detail-back-bar";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ fit_report_id: string }>;
}

export default async function FitReportPage({ params }: PageProps) {
  const { fit_report_id } = await params;
  const token = await getServerToken();
  const t = await getTranslations("fitReport");

  const report = await getFitReport(fit_report_id, token).catch(() => null);
  if (!report) notFound();

  const [job, profile] = await Promise.all([
    getJob(report.job_id, token).catch(() => null),
    getProfile(token).catch(() => null),
  ]);

  return (
    <>
      {/* Title and job identity live in the 56px bar, not in the body: the bar
          used to hold nothing but a back link on a 1024px page, and the job
          line appeared twice (once under the h1, once in the score card's
          footer). */}
      <DetailBackBar
        backHref={job ? `/jobs/${report.job_id}` : "/"}
        backLabel={job ? t("backToJobDetail") : t("backToInboxShort")}
        title={t("title")}
        meta={job ? `${job.title} · ${job.company}${job.location ? ` · ${job.location}` : ""}` : undefined}
      />

      <div className="flex-1 overflow-y-auto">
        <PageContainer variant="wide" className="space-y-[var(--space-stack-lg)]">
          <FitReportTabs report={report} job={job} profile={profile} />
        </PageContainer>
      </div>
    </>
  );
}
