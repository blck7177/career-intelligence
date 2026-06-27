import Link from "next/link";
import { notFound } from "next/navigation";
import { getFitReport, getJob, getProfile } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { FitReportTabs } from "@/components/FitReportTabs";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ fit_report_id: string }>;
}

export default async function FitReportPage({ params }: PageProps) {
  const { fit_report_id } = await params;
  const token = await getServerToken();

  const report = await getFitReport(fit_report_id, token).catch(() => null);
  if (!report) notFound();

  const [job, profile] = await Promise.all([
    getJob(report.job_id, token).catch(() => null),
    getProfile(token).catch(() => null),
  ]);

  return (
    <>
      <header
        className="h-[52px] flex items-center px-7 bg-white shrink-0 gap-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Link
          href={job ? `/jobs/${report.job_id}` : "/"}
          className="text-[13px] hover:underline"
          style={{ color: "var(--primary)" }}
        >
          ← Back to {job ? "Job Detail" : "Inbox"}
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto px-7 py-6">
        <div className="max-w-4xl space-y-6">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold" style={{ color: "oklch(16% 0.015 275)" }}>
              Candidate Fit Report
            </h1>
            {job && (
              <p className="text-sm" style={{ color: "oklch(52% 0.01 275)" }}>
                {job.title} · {job.company}
                {job.location && <> · {job.location}</>}
              </p>
            )}
          </div>

          <FitReportTabs report={report} job={job} profile={profile} />
        </div>
      </div>
    </>
  );
}
