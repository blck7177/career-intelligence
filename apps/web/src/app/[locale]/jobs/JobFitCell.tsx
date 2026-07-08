"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { FitButton } from "@/components/FitButton";
import { bandOf, BAND } from "@/lib/matchBand";

interface JobFitCellProps {
  jobId: string;
  jobReportId?: string | null;
  hasProfile: boolean;
  fitReport?: {
    id: string;
    score: number;
    recommended_next_action?: string | null;
  };
}

function FitScoreBadge({ fitReportId, score }: { fitReportId: string; score: number }) {
  const t = useTranslations("jobFit");
  const band = BAND[bandOf(score)];
  return (
    <Link
      href={`/fit-reports/${fitReportId}`}
      className="text-xs font-semibold px-2 py-0.5 rounded-full hover:opacity-80 transition-opacity"
      style={{ backgroundColor: band.bg, color: band.fg }}
    >
      {t("percentFit", { score })}
    </Link>
  );
}

const ACTION_KEY_MAP: Record<string, string> = {
  "apply now": "applyNow",
  "revise resume first": "reviseResume",
  "get more context": "getContext",
  skip: "skip",
};

export function JobFitCell({ jobId, jobReportId, hasProfile, fitReport }: JobFitCellProps) {
  const t = useTranslations("jobFit");

  if (!hasProfile) return null;

  if (fitReport) {
    const actionKey = fitReport.recommended_next_action ? ACTION_KEY_MAP[fitReport.recommended_next_action] : undefined;
    return (
      <div className="flex flex-col items-end gap-1">
        <FitScoreBadge fitReportId={fitReport.id} score={fitReport.score} />
        {fitReport.recommended_next_action && (
          <span className="text-2xs text-[var(--ink-muted)] max-w-[130px] text-right leading-tight">
            {actionKey ? t(actionKey) : fitReport.recommended_next_action}
          </span>
        )}
      </div>
    );
  }

  if (jobReportId) {
    return (
      <FitButton
        jobId={jobId}
        jobReportId={jobReportId}
        size="sm"
        variant="outline"
        label={t("analyzeFit")}
      />
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <FitButton
        jobId={jobId}
        disabled
        size="sm"
        variant="outline"
        label={t("analyzeFit")}
      />
      <span className="text-2xs text-[var(--ink-muted)]">{t("needsReport")}</span>
    </div>
  );
}
