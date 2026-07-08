"use client";

import { useEffect, useState } from "react";
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
import { type Band, bandOf, BAND, THEME_CHIP } from "@/lib/matchBand";
import { CompositionBar } from "@/components/CompositionBar";
import { Metric } from "@/components/ui/metric";
import { useCountUp } from "@/hooks/useCountUp";
import { TabsRoot, TabsList, Tab, TabsIndicator, TabsPanel } from "@/components/ui/tabs";

type T = ReturnType<typeof useTranslations>;

// ---------------------------------------------------------------------------
// ScoreGauge — radial meter (ratio against the 0-100 limit), animated on mount.
// ---------------------------------------------------------------------------

function ScoreGauge({ score, t }: { score: number; t: T }) {
  const band = bandOf(score);
  const label =
    band === "strong" ? t("strongMatch") : band === "partial" ? t("partialMatch") : t("significantGaps");

  const size = 116;
  const stroke = 10;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;

  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setProgress(Math.max(0, Math.min(100, score))));
    return () => cancelAnimationFrame(raf);
  }, [score]);

  const displayScore = useCountUp(score, { initial: 0, durationMs: 800 });
  const offset = circumference * (1 - progress / 100);

  return (
    <div className="flex items-center gap-5">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={BAND[band].track}
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={BAND[band].ring}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <Metric size="hero" style={{ color: BAND[band].fg }}>{displayScore}</Metric>
          <span className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>
            / 100
          </span>
        </div>
      </div>
      <div>
        <Badge
          className="border-0 text-xs font-semibold"
          style={{ backgroundColor: BAND[band].bg, color: BAND[band].fg }}
        >
          {label}
        </Badge>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MatchCompositionBar / SeverityMiniBar — thin wrappers around the shared
// CompositionBar, translating this report's data into generic segments.
// ---------------------------------------------------------------------------

function MatchCompositionBar({ strong, partial, gaps, t }: { strong: number; partial: number; gaps: number; t: T }) {
  return (
    <CompositionBar
      className="mt-4"
      ariaLabel={t("matchComposition")}
      segments={[
        { key: "strong", count: strong, label: t("strongMatches"), color: BAND.strong.ring },
        { key: "partial", count: partial, label: t("partialMatches"), color: BAND.partial.ring },
        { key: "gaps", count: gaps, label: t("gaps"), color: BAND.gaps.ring },
      ]}
    />
  );
}

function SeverityMiniBar({ gaps, t }: { gaps: { severity: string }[]; t: T }) {
  const counts = { blocking: 0, significant: 0, minor: 0 };
  for (const g of gaps) {
    if (g.severity === "blocking") counts.blocking++;
    else if (g.severity === "significant") counts.significant++;
    else counts.minor++;
  }
  return (
    <CompositionBar
      compact
      className="ml-auto"
      ariaLabel="gap severity breakdown"
      segments={[
        { key: "blocking", count: counts.blocking, label: t("blocking"), color: BAND.gaps.ring },
        { key: "significant", count: counts.significant, label: t("significant"), color: BAND.partial.ring },
        { key: "minor", count: counts.minor, label: t("minor"), color: "var(--ink-faint)" },
      ]}
    />
  );
}

function ActionBadge({ action, t }: { action: string; t: T }) {
  const key = action.toLowerCase();
  if (key === "apply now")
    return (
      <Badge className="border-0 text-xs font-semibold" style={{ backgroundColor: BAND.strong.bg, color: BAND.strong.fg }}>
        {t("applyNow")}
      </Badge>
    );
  if (key === "revise resume first")
    return (
      <Badge className="border-0 text-xs font-semibold" style={{ backgroundColor: BAND.partial.bg, color: BAND.partial.fg }}>
        {t("reviseResumeFirst")}
      </Badge>
    );
  if (key === "get more context")
    return <Badge className={`border-0 text-xs font-semibold ${THEME_CHIP}`}>{t("getMoreContext")}</Badge>;
  if (key === "skip") return <Badge variant="secondary" className="border-0 text-xs font-semibold">{t("skip")}</Badge>;
  return <Badge variant="secondary" className="border-0 text-xs font-semibold">{action}</Badge>;
}

function SeverityBadge({ severity, t }: { severity: string; t: T }) {
  if (severity === "blocking")
    return (
      <Badge className="border-0 text-xs" style={{ backgroundColor: BAND.gaps.bg, color: BAND.gaps.fg }}>
        {t("blocking")}
      </Badge>
    );
  if (severity === "significant")
    return (
      <Badge className="border-0 text-xs" style={{ backgroundColor: BAND.partial.bg, color: BAND.partial.fg }}>
        {t("significant")}
      </Badge>
    );
  return <Badge variant="secondary" className="border-0 text-xs">{t("minor")}</Badge>;
}

type Tone = Band | "theme";

function Section({
  icon: Icon,
  title,
  children,
  count,
  tone = "theme",
  headerExtra,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
  count?: number;
  tone?: Tone;
  headerExtra?: React.ReactNode;
}) {
  const chipClassName = tone === "theme" ? THEME_CHIP : undefined;
  const chipStyle = tone !== "theme" ? { backgroundColor: BAND[tone].bg, color: BAND[tone].fg } : undefined;
  return (
    <Card className="shadow-sm hover:shadow-md transition-shadow duration-200 rounded-xl">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2.5 text-sm font-semibold">
          <span
            className={`flex items-center justify-center w-7 h-7 rounded-full shrink-0 ${chipClassName ?? ""}`}
            style={chipStyle}
          >
            <Icon size={14} />
          </span>
          {title}
          {count !== undefined && (
            <Badge variant="secondary" className="text-xs font-normal ml-1">
              {count}
            </Badge>
          )}
          {headerExtra}
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

  const band = bandOf(score);

  return (
    <div className="space-y-6">
      {/* Score card */}
      <Card
        className="rounded-xl shadow-sm overflow-hidden relative"
        style={{ borderTop: `3px solid ${BAND[band].ring}` }}
      >
        <CardContent>
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="space-y-3">
              <ScoreGauge score={score} t={t} />
              {s.recommended_next_action && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--ink-muted)]">{t("recommendedAction")}</span>
                  <ActionBadge action={s.recommended_next_action} t={t} />
                </div>
              )}
            </div>
            {s.match_summary && (
              <div className="sm:max-w-md text-sm text-[var(--ink-muted)] leading-relaxed">
                {s.match_summary}
              </div>
            )}
          </div>

          <MatchCompositionBar
            strong={s.strong_matches?.length ?? 0}
            partial={s.partial_matches?.length ?? 0}
            gaps={s.gaps?.length ?? 0}
            t={t}
          />

          <div className="flex flex-wrap gap-3 mt-4 pt-4 border-t text-xs text-[var(--ink-muted)]">
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
              {t("reportIdLabel")}<code className="bg-[var(--muted)] px-1 rounded">{report.id}</code>
            </span>
          </div>
        </CardContent>
      </Card>

      <TabsRoot value={tab} onValueChange={(v) => setTab(v as "analysis" | "positioning")}>
        <TabsList>
          {tabs.map((tabItem) => (
            <Tab key={tabItem.id} value={tabItem.id}>
              {tabItem.label}
            </Tab>
          ))}
          <TabsIndicator />
        </TabsList>

        <TabsPanel value="analysis" className="space-y-4 animate-fade-in-up pt-4">
          {(s.strong_matches?.length ?? 0) > 0 && (
            <Section icon={CheckCircle2} title={t("strongMatches")} count={s.strong_matches!.length} tone="strong">
              <div className="space-y-3">
                {s.strong_matches!.map((m, i) => (
                  <div
                    key={i}
                    className="rounded-md p-3 transition-colors"
                    style={{ backgroundColor: BAND.strong.bg, borderLeft: `2px solid ${BAND.strong.border}` }}
                  >
                    <p className="text-sm font-medium" style={{ color: BAND.strong.fg }}>{m.demand}</p>
                    {m.evidence && (
                      <p className="text-xs text-[var(--ink-muted)] mt-1 leading-relaxed">{m.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.partial_matches?.length ?? 0) > 0 && (
            <Section icon={AlertTriangle} title={t("partialMatches")} count={s.partial_matches!.length} tone="partial">
              <div className="space-y-3">
                {s.partial_matches!.map((m, i) => (
                  <div
                    key={i}
                    className="rounded-md p-3 transition-colors"
                    style={{ backgroundColor: BAND.partial.bg, borderLeft: `2px solid ${BAND.partial.border}` }}
                  >
                    <p className="text-sm font-medium" style={{ color: BAND.partial.fg }}>{m.demand}</p>
                    {m.gap_description && (
                      <p className="text-xs text-[var(--ink-muted)] mt-1 leading-relaxed">{m.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.gaps?.length ?? 0) > 0 && (
            <Section
              icon={XCircle}
              title={t("gaps")}
              count={s.gaps!.length}
              tone="gaps"
              headerExtra={<SeverityMiniBar gaps={s.gaps!} t={t} />}
            >
              <div className="space-y-3">
                {s.gaps!.map((g, i) => (
                  <div
                    key={i}
                    className="rounded-md p-3 transition-colors"
                    style={{ backgroundColor: BAND.gaps.bg, borderLeft: `2px solid ${BAND.gaps.border}` }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium" style={{ color: BAND.gaps.fg }}>{g.demand}</p>
                      <SeverityBadge severity={g.severity} t={t} />
                    </div>
                    {g.gap_description && (
                      <p className="text-xs text-[var(--ink-muted)] mt-1 leading-relaxed">{g.gap_description}</p>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {(s.risk_flags?.length ?? 0) > 0 && (
            <Section icon={Flag} title={t("riskFlags")} count={s.risk_flags!.length} tone="theme">
              <ul className="space-y-2">
                {s.risk_flags!.map((flag, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-[var(--ink-secondary)]">
                    <Flag size={13} className="mt-0.5 shrink-0 text-[var(--ink-muted)]" />
                    {flag}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {(s.interview_talking_points?.length ?? 0) > 0 && (
            <Section icon={MessageSquare} title={t("interviewTalkingPoints")} tone="theme">
              <ol className="space-y-2 list-none">
                {s.interview_talking_points!.map((point, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-[var(--muted)] flex items-center justify-center text-xs font-semibold text-[var(--ink-muted)]">
                      {i + 1}
                    </span>
                    <span className="leading-relaxed">{point}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </TabsPanel>

        <TabsPanel value="positioning" className="space-y-4 animate-fade-in-up pt-4">
          {strategy?.positioning ? (
            <>
              <Section icon={FileEdit} title={t("resumePositioningGuidance")} tone="theme">
                <p className="text-sm leading-relaxed text-[var(--ink-primary)]">{strategy.positioning}</p>
              </Section>

              {(strategy.keywords_to_add?.length ?? 0) > 0 && (
                <Section
                  icon={Tags}
                  title={t("keywordsToAdd")}
                  count={strategy.keywords_to_add!.length}
                  tone="theme"
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
                <Section icon={Lightbulb} title={t("evidenceToSurface")} tone="theme">
                  <ul className="space-y-2">
                    {strategy.evidence_to_surface!.map((item, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm">
                        <ChevronRight size={14} className="shrink-0 mt-0.5 text-[var(--ink-muted)]" />
                        <span className="leading-relaxed">{item}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          ) : (
            <p className="text-sm text-[var(--ink-muted)]">{t("noPositioningGuidance")}</p>
          )}
        </TabsPanel>
      </TabsRoot>
    </div>
  );
}
