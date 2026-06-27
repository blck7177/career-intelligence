"use client";

import Link from "next/link";
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
  return (
    <Link
      href={`/fit-reports/${fitReportId}`}
      className={`text-xs font-semibold px-2 py-0.5 rounded-full ${fitScoreClass(score)} hover:opacity-80 transition-opacity`}
    >
      {score}% fit
    </Link>
  );
}

function actionLabel(action: string): string {
  const MAP: Record<string, string> = {
    "apply now": "Apply now",
    "revise resume first": "Revise resume",
    "get more context": "Get context",
    skip: "Skip",
  };
  return MAP[action] ?? action;
}

export function JobFitCell({ jobId, jobReportId, hasProfile, fitReport }: JobFitCellProps) {
  if (!hasProfile) return null;

  if (fitReport) {
    return (
      <div className="flex flex-col items-end gap-1">
        <FitScoreBadge fitReportId={fitReport.id} score={fitReport.score} />
        {fitReport.recommended_next_action && (
          <span className="text-[10px] text-zinc-400 max-w-[120px] text-right leading-tight">
            {actionLabel(fitReport.recommended_next_action)}
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
        label="Analyze fit"
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
        label="Analyze fit"
      />
      <span className="text-[10px] text-zinc-400">Needs report</span>
    </div>
  );
}
