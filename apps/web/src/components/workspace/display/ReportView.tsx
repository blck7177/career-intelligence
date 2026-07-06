"use client";

import { useState, useEffect } from "react";
import { getRunReport } from "@/api/client";
import type { JobReportResponse, FitReportResponse, RunRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScoreBadge, SeverityChip } from "@/components/MatchVisuals";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { FileText, AlertTriangle, HelpCircle, Building2, Compass, Workflow, ListChecks, StickyNote } from "lucide-react";
import { JobReportContent, type JobReportLabels } from "@/components/JobReportContent";

interface ReportViewProps {
  run: RunRead;
}

const JOB_REPORT_ICONS = {
  businessContext: Building2,
  positionFunction: Compass,
  dailyWorkflow: Workflow,
  skillDemands: ListChecks,
  analystNotes: StickyNote,
};

const JOB_REPORT_LABELS: JobReportLabels = {
  businessContext: "Business Context",
  positionFunction: "Position Function",
  dailyWorkflow: "Daily Workflow",
  likelyInputs: "Inputs",
  typicalAnalyses: "Typical Analyses",
  outputs: "Outputs",
  keySkillDemands: "Key Skill Demands",
  core: "Core",
  supporting: "Supporting",
  other: "Other",
  analystNotes: "Analyst Notes",
  uncertaintyNotes: "Uncertainty Notes",
  confidence: "Confidence",
  problemSolved: (text) => `Problem solved: ${text}`,
};

function JobReportCard({ report }: { report: JobReportResponse }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
          Job Intelligence Report
          <Badge variant="match-strong" className="text-xs">{report.status}</Badge>
          {report.used_research && (
            <Badge variant="match-good" className="text-xs">with research</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <JobReportContent report={report} labels={JOB_REPORT_LABELS} icons={JOB_REPORT_ICONS} />
      </CardContent>
    </Card>
  );
}

function FitReportContent({ report }: { report: FitReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  const matchSummary = s.match_summary as string | undefined;
  const strongMatches = (s.strong_matches as { demand: string; evidence: string }[]) ?? [];
  const gaps = (s.gaps as { demand: string; gap_description: string; severity: string }[]) ?? [];
  const riskFlags = (s.risk_flags as string[]) ?? [];
  const talkingPoints = (s.interview_talking_points as string[]) ?? [];
  const nextAction = s.recommended_next_action as string | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
          Candidate Fit Report
          <ScoreBadge score={report.overall_match_score} />
          <Badge variant="match-strong" className="text-xs">{report.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-xs text-[var(--ink-secondary)]">
        {matchSummary && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-0.5">Summary</p>
            <p className="leading-relaxed">{matchSummary}</p>
          </div>
        )}
        {nextAction && (
          <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 flex items-center gap-2">
            <p className="font-medium text-blue-700">Recommended action:</p>
            <p className="text-blue-700 font-semibold">{nextAction}</p>
          </div>
        )}
        {strongMatches.length > 0 && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-1">
              Strong Matches (top {Math.min(strongMatches.length, 3)})
            </p>
            <ul className="space-y-1">
              {strongMatches.slice(0, 3).map((m, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-emerald-500 shrink-0">✓</span>
                  <span>
                    <span className="font-medium">{m.demand}</span> — {m.evidence}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {gaps.length > 0 && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-1">Gaps</p>
            <ul className="space-y-1.5">
              {gaps.map((g, i) => (
                <li key={i} className="flex gap-2 items-start">
                  <SeverityChip severity={g.severity} />
                  <span>
                    <span className="font-medium">{g.demand}</span> — {g.gap_description}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {riskFlags.length > 0 && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-1">Risk Flags</p>
            <ul className="space-y-0.5">
              {riskFlags.map((f, i) => (
                <li key={i} className="flex gap-1.5 items-start text-amber-700">
                  <span>⚠</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {talkingPoints.length > 0 && (
          <div>
            <p className="font-medium text-[var(--ink-muted)] mb-1">Interview Talking Points</p>
            <ol className="space-y-0.5 list-decimal list-inside">
              {talkingPoints.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}
        <p className="text-[var(--ink-muted)] pt-1">
          Report ID: {report.id} · Job Report: {report.job_report_id} · v{report.prompt_version}
        </p>
      </CardContent>
    </Card>
  );
}

export function ReportView({ run }: ReportViewProps) {
  const [report, setReport] = useState<JobReportResponse | FitReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getRunReport(run.id)
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load report"))
      .finally(() => setLoading(false));
  }, [run.id]);

  if (loading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-6 w-40 rounded-lg" />
        <div className="space-y-2">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3.5 w-32" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
        <AlertTriangle size={12} className="shrink-0" />
        {error}
      </p>
    );
  }

  if (!report) {
    return <EmptyState icon={FileText} title="No report available." compact />;
  }

  if (run.run_type === "job_report") {
    return <JobReportCard report={report as JobReportResponse} />;
  }

  if (run.run_type === "fit_report") {
    return <FitReportContent report={report as FitReportResponse} />;
  }

  return <EmptyState icon={HelpCircle} title="Unknown report type." compact />;
}
