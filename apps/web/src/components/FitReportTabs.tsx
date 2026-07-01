"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { FitReportResponse, JobRead, ProfileRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Flag,
  MessageSquare,
  FileEdit,
  Tags,
  Lightbulb,
  ChevronRight,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type T = ReturnType<typeof useTranslations>;

function ScoreRing({ score, t }: { score: number; t: T }) {
  const color =
    score >= 70 ? "text-[var(--match-strong-fg)]" : score >= 50 ? "text-amber-600" : "text-rose-600";
  const label =
    score >= 70 ? t("strongMatch") : score >= 50 ? t("partialMatch") : t("significantGaps");
  return (
    <div className="flex items-center gap-4">
      <div className={`text-5xl font-bold tabular-nums ${color}`}>{score}</div>
      <div>
        <div className="text-sm font-medium" style={{ color: "oklch(56% 0.01 275)" }}>/ 100</div>
        <Badge
          className={`mt-1 border-0 text-xs font-semibold ${
            score >= 70
              ? "bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]"
              : score >= 50
              ? "bg-amber-100 text-amber-800"
              : "bg-rose-100 text-rose-800"
          }`}
        >
          {label}
        </Badge>
      </div>
    </div>
  );
}

function ActionBadge({ action, t }: { action: string; t: T }) {
  const config: Record<string, { label: string; cls: string }> = {
    "apply now": { label: t("applyNow"), cls: "bg-emerald-100 text-emerald-800" },
    "revise resume first": { label: t("reviseResumeFirst"), cls: "bg-amber-100 text-amber-800" },
    "get more context": { label: t("getMoreContext"), cls: "bg-blue-100 text-blue-800" },
    skip: { label: t("skip"), cls: "bg-zinc-100 text-zinc-700" },
  };
  const c = config[action.toLowerCase()] ?? { label: action, cls: "bg-zinc-100 text-zinc-700" };
  return <Badge className={`${c.cls} border-0 text-xs font-semibold`}>{c.label}</Badge>;
}

function SeverityBadge({ severity, t }: { severity: string; t: T }) {
  if (severity === "blocking")
    return <Badge className="bg-rose-100 text-rose-800 border-0 text-xs">{t("blocking")}</Badge>;
  if (severity === "significant")
    return <Badge className="bg-amber-100 text-amber-800 border-0 text-xs">{t("significant")}</Badge>;
  return <Badge className="bg-zinc-100 text-zinc-700 border-0 text-xs">{t("minor")}</Badge>;
}

function Section({
  icon: Icon,
  title,
  children,
  count,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          <Icon size={16} className="text-zinc-400" />
          {title}
          {count !== undefined && (
            <Badge variant="secondary" className="text-xs font-normal ml-1">
              {count}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

type Structured = {
  overall_match_score?: number;
  match_summary?: string;
  recommended_next_action?: string;
  analyzed_at?: string;
  prompt_version?: string;
  strong_matches?: { demand: string; evidence?: string }[];
  partial_matches?: { demand: string; gap_description?: string }[];
  gaps?: { demand: string; gap_description?: string; severity: string }[];
  risk_flags?: string[];
  interview_talking_points?: string[];
  resume_rewrite_strategy?: {
    positioning?: string;
    keywords_to_add?: string[];
    evidence_to_surface?: string[];
  };
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface FitReportTabsProps {
  report: FitReportResponse;
  job: JobRead | null;
  profile: ProfileRead | null;
}

export function FitReportTabs({ report, job, profile }: FitReportTabsProps) {
  const t = useTranslations("fitReport");
  const [tab, setTab] = useState<"analysis" | "positioning">("analysis");
  const s = report.structured_json as Structured;
  const score = report.overall_match_score ?? s.overall_match_score ?? 0;
  const strategy = s.resume_rewrite_strategy;

  const tabs = [
    { id: "analysis" as const, label: t("matchAnalysisTab") },
    { id: "positioning" as const, label: t("resumePositioningTab") },
  ];

  return (
    <div className="space-y-6">
      {/* Score card */}
      <Card>
        <CardContent className="pt-6 pb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="space-y-3">
              <ScoreRing score={score} t={t} />
              {s.recommended_next_action && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-zinc-500">{t("recommendedAction")}</span>
                  <ActionBadge action={s.recommended_next_action} t={t} />
                </div>
              )}
            </div>
            {s.match_summary && (
              <div className="sm:max-w-md text-sm text-zinc-500 leading-relaxed">
                {s.match_summary}
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t text-xs text-zinc-400">
            {job && (
              <span>
                {job.title} · {job.company}
              </span>
            )}
            {profile && profile.years_experience != null && (
              <span>{t("yearsExperience", { count: profile.years_experience })}</span>
            )}
            {s.analyzed_at && <span>{new Date(s.analyzed_at).toLocaleDateString()}</span>}
            <span>
              {t("reportIdLabel")}<code className="bg-zinc-100 px-1 rounded">{report.id}</code>
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-zinc-200">
        {tabs.map((tabItem) => (
          <button
            key={tabItem.id}
            type="button"
            onClick={() => setTab(tabItem.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === tabItem.id
                ? "border-[var(--primary)] text-[var(--secondary-foreground)]"
                : "border-transparent text-zinc-500 hover:text-zinc-800"
            }`}
          >
            {tabItem.label}
          </button>
        ))}
      </div>

      {tab === "analysis" && (
        <div className="space-y-4">
          {(s.strong_matches?.length ?? 0) > 0 && (
            <Section icon={CheckCircle2} title={t("strongMatches")} count={s.strong_matches!.length}>
              <div className="space-y-3">
                {s.strong_matches!.map((m, i) => (
                  <div key={i} className="border rounded-md p-3 bg-emerald-50/40">
                    <p className="text-sm font-medium text-emerald-900">{m.demand}</p>
                    {m.evidence && (
                      <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{m.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.partial_matches?.length ?? 0) > 0 && (
            <Section icon={AlertTriangle} title={t("partialMatches")} count={s.partial_matches!.length}>
              <div className="space-y-3">
                {s.partial_matches!.map((m, i) => (
                  <div key={i} className="border rounded-md p-3 bg-amber-50/40">
                    <p className="text-sm font-medium text-amber-900">{m.demand}</p>
                    {m.gap_description && (
                      <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{m.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.gaps?.length ?? 0) > 0 && (
            <Section icon={XCircle} title={t("gaps")} count={s.gaps!.length}>
              <div className="space-y-3">
                {s.gaps!.map((g, i) => (
                  <div key={i} className="border rounded-md p-3 bg-rose-50/30">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-rose-900">{g.demand}</p>
                      <SeverityBadge severity={g.severity} t={t} />
                    </div>
                    {g.gap_description && (
                      <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{g.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.risk_flags?.length ?? 0) > 0 && (
            <Section icon={Flag} title={t("riskFlags")} count={s.risk_flags!.length}>
              <ul className="space-y-2">
                {s.risk_flags!.map((flag, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-rose-700">
                    <Flag size={13} className="mt-0.5 shrink-0" />
                    {flag}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {(s.interview_talking_points?.length ?? 0) > 0 && (
            <Section icon={MessageSquare} title={t("interviewTalkingPoints")}>
              <ol className="space-y-2 list-none">
                {s.interview_talking_points!.map((point, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-zinc-100 flex items-center justify-center text-xs font-semibold text-zinc-500">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{point}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}

      {tab === "positioning" && (
        <div className="space-y-4">
          {strategy?.positioning ? (
            <>
              <Section icon={FileEdit} title={t("resumePositioningGuidance")}>
                <p className="text-sm leading-relaxed text-zinc-800">{strategy.positioning}</p>
              </Section>

              {(strategy.keywords_to_add?.length ?? 0) > 0 && (
                <Section
                  icon={Tags}
                  title={t("keywordsToAdd")}
                  count={strategy.keywords_to_add!.length}
                >
                  <div className="flex flex-wrap gap-2">
                    {strategy.keywords_to_add!.map((kw) => (
                      <Badge key={kw} variant="secondary" className="text-xs font-normal">
                        {kw}
                      </Badge>
                    ))}
                  </div>
                </Section>
              )}

              {(strategy.evidence_to_surface?.length ?? 0) > 0 && (
                <Section icon={Lightbulb} title={t("evidenceToSurface")}>
                  <ul className="space-y-2">
                    {strategy.evidence_to_surface!.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        <ChevronRight size={14} className="shrink-0 mt-0.5 text-zinc-400" />
                        <span className="leading-relaxed">{item}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          ) : (
            <p className="text-sm text-zinc-500">{t("noPositioningGuidance")}</p>
          )}
        </div>
      )}
    </div>
  );
}
