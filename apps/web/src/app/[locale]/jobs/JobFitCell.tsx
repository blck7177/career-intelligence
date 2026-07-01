"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { FitButton } from "@/components/FitButton";

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

function fitScoreClass(score: number): string {
  if (score >= 75) return "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]";
  if (score >= 50) return "bg-[var(--match-good-bg)] text-[var(--match-good-fg)]";
  return "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]";
}

function FitScoreBadge({ fitReportId, score }: { fitReportId: string; score: number }) {
  const t = useTranslations("jobFit");
  return (
    <Link
      href={`/fit-reports/${fitReportId}`}
      className={`text-xs font-semibold px-2 py-0.5 rounded-full ${fitScoreClass(score)} hover:opacity-80 transition-opacity`}
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
          <span className="text-[11px] text-zinc-400 max-w-[130px] text-right leading-tight">
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
      <span className="text-[11px] text-zinc-400">{t("needsReport")}</span>
    </div>
  );
}
