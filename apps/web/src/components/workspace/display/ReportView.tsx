"use client";

import { useState, useEffect } from "react";
import { getRunReport } from "@/api/client";
import type { JobReportResponse, FitReportResponse, RunRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReportViewProps {
  run: RunRead;
}

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 80
      ? "bg-emerald-100 text-emerald-700"
      : score >= 60
      ? "bg-amber-100 text-amber-700"
      : "bg-rose-100 text-rose-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {score}/100
    </span>
  );
}

function SeverityChip({ severity }: { severity: string }) {
  const color =
    severity === "blocking"
      ? "bg-rose-100 text-rose-700"
      : severity === "significant"
      ? "bg-amber-100 text-amber-700"
      : "bg-zinc-100 text-zinc-600";
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
      {severity}
    </span>
  );
}

function JobReportContent({ report }: { report: JobReportResponse }) {
  const s = report.structured_json as Record<string, unknown>;
  const primaryRoleCategory = s.primary_role_category as string | undefined;
  const businessContext = s.business_context as string | undefined;
  const positionFunction = s.position_function as string | undefined;
  const uncertaintyNotes = s.uncertainty_notes as string | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2 flex-wrap">
          Job Intelligence Report
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
          {report.used_research && (
            <Badge className="bg-blue-100 text-blue-700 text-xs">with research</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-zinc-700">
        {primaryRoleCategory && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Role category</p>
            <p>{primaryRoleCategory}</p>
          </div>
        )}
        {businessContext && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Business Context</p>
            <p className="leading-relaxed">{businessContext}</p>
          </div>
        )}
        {positionFunction && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Position Function</p>
            <p className="leading-relaxed">{positionFunction}</p>
          </div>
        )}
        {uncertaintyNotes && (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="font-medium text-amber-700 mb-0.5">Uncertainty Notes</p>
            <p className="text-amber-700">{uncertaintyNotes}</p>
          </div>
        )}
        <p className="text-zinc-400 pt-1">
          Report ID: {report.id} · v{report.prompt_version}
        </p>
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
          <Badge className="bg-emerald-100 text-emerald-700 text-xs">{report.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-xs text-zinc-700">
        {matchSummary && (
          <div>
            <p className="font-medium text-zinc-500 mb-0.5">Summary</p>
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
            <p className="font-medium text-zinc-500 mb-1">
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
            <p className="font-medium text-zinc-500 mb-1">Gaps</p>
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
            <p className="font-medium text-zinc-500 mb-1">Risk Flags</p>
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
            <p className="font-medium text-zinc-500 mb-1">Interview Talking Points</p>
            <ol className="space-y-0.5 list-decimal list-inside">
              {talkingPoints.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </div>
        )}
        <p className="text-zinc-400 pt-1">
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

  if (loading) return <p className="text-xs text-zinc-400 py-4 text-center">Loading report…</p>;

  if (error) {
    return (
      <p className="text-xs text-rose-600 rounded border border-rose-200 bg-rose-50 px-3 py-2">
        {error}
      </p>
    );
  }

  if (!report) {
    return <p className="text-xs text-zinc-400 py-4 text-center">No report available.</p>;
  }

  if (run.run_type === "job_report") {
    return <JobReportContent report={report as JobReportResponse} />;
  }

  if (run.run_type === "fit_report") {
    return <FitReportContent report={report as FitReportResponse} />;
  }

  return <p className="text-xs text-zinc-400 py-4 text-center">Unknown report type.</p>;
}
