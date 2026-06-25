import Link from "next/link";
import { notFound } from "next/navigation";
import { getFitReport, getJob, getProfile } from "@/api/client";
import { getServerToken } from "@/lib/server-auth";
import { FitReportTabs } from "@/components/FitReportTabs";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

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
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <Link
        href={job ? `/jobs/${report.job_id}` : "/jobs"}
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900"
      >
        <ArrowLeft size={14} /> Back to {job ? "Job Detail" : "Role Inbox"}
      </Link>

      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-zinc-900">Candidate Fit Report</h1>
        {job && (
          <p className="text-zinc-500 text-sm">
            {job.title} · {job.company}
            {job.location && <> · {job.location}</>}
          </p>
        )}
      </div>

      <FitReportTabs report={report} job={job} profile={profile} />

      <div className="flex items-center gap-3 pt-2 border-t">
        {job && (
          <Link href={`/jobs/${report.job_id}`}>
            <Button size="sm" variant="outline">
              View Job Detail
            </Button>
          </Link>
        )}
        <Link href="/jobs">
          <Button size="sm" variant="ghost">
            Role Inbox
          </Button>
        </Link>
      </div>
    </div>
  );
}
