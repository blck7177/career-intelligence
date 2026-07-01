"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { JobRead, JobReportResponse, FitReportResponse, JDStructured, ProfileRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { FitReportTabs } from "@/components/FitReportTabs";

type RightTab = "intelligence" | "fit";

interface JobDetailTabsProps {
  job: JobRead;
  jd: JDStructured | null;
  jobReport: JobReportResponse | null;
  fitReport: FitReportResponse | null;
  profile: ProfileRead | null;
  actions: React.ReactNode;
}

/* ── Shared ── */

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "oklch(60% 0.01 275)" }}>
      {children}
    </p>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed" style={{ color: "oklch(36% 0.01 275)" }}>
          <span className="shrink-0 mt-0.5" style={{ color: "oklch(72% 0.01 275)" }}>·</span>
          {item}
        </li>
      ))}
    </ul>
  );
}

function TagList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className="px-2.5 py-1 rounded-md text-[11px] font-medium" style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>
          {item}
        </span>
      ))}
    </div>
  );
}

/* ── Left: JD Panel ── */

function JDPanel({ jd }: { jd: JDStructured | null }) {
  const t = useTranslations("jobDetail");

  if (!jd) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>{t("noJdData")}</p>
        <p className="text-xs mt-1" style={{ color: "oklch(60% 0.01 275)" }}>
          {t("noJdDataHint")}
        </p>
      </div>
    );
  }

  const hasContent =
    jd.responsibilities.length > 0 ||
    jd.required_skills.length > 0 ||
    jd.preferred_skills.length > 0 ||
    jd.likely_tasks.length > 0;

  if (!hasContent) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>{t("noJdExtracted")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {jd.inferred_team_context && (
        <div>
          <SectionTitle>{t("teamContext")}</SectionTitle>
          <p className="text-[13px] leading-relaxed" style={{ color: "oklch(36% 0.01 275)" }}>
            {jd.inferred_team_context}
          </p>
        </div>
      )}

      {jd.responsibilities.length > 0 && (
        <div>
          <SectionTitle>{t("responsibilities")}</SectionTitle>
          <BulletList items={jd.responsibilities} />
        </div>
      )}

      {(jd.required_skills.length > 0 || jd.preferred_skills.length > 0) && (
        <div className="grid grid-cols-2 gap-4">
          {jd.required_skills.length > 0 && (
            <div>
              <SectionTitle>{t("requiredSkills")}</SectionTitle>
              <BulletList items={jd.required_skills} />
            </div>
          )}
          {jd.preferred_skills.length > 0 && (
            <div>
              <SectionTitle>{t("preferredSkills")}</SectionTitle>
              <BulletList items={jd.preferred_skills} />
            </div>
          )}
        </div>
      )}

      {(jd.likely_tasks.length > 0 || jd.likely_stakeholders.length > 0) && (
        <div className="grid grid-cols-2 gap-4">
          {jd.likely_tasks.length > 0 && (
            <div>
              <SectionTitle>{t("likelyTasks")}</SectionTitle>
              <BulletList items={jd.likely_tasks} />
            </div>
          )}
          {jd.likely_stakeholders.length > 0 && (
            <div>
              <SectionTitle>{t("stakeholders")}</SectionTitle>
              <BulletList items={jd.likely_stakeholders} />
            </div>
          )}
        </div>
      )}

      {jd.tools_mentioned.length > 0 && (
        <div>
          <SectionTitle>{t("toolsAndTech")}</SectionTitle>
          <TagList items={jd.tools_mentioned} />
        </div>
      )}
    </div>
  );
}

/* ── Right: Intelligence Report ── */

function IntelligencePanel({ report }: { report: JobReportResponse | null }) {
  const t = useTranslations("jobDetail");

  if (!report) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>{t("noIntelligenceReport")}</p>
        <p className="text-xs mt-2" style={{ color: "oklch(60% 0.01 275)" }}>
          {t("noIntelligenceReportHint")}
        </p>
      </div>
    );
  }

  const s = report.structured_json as Record<string, unknown>;
  const bc = s.business_context as { summary?: string; problem_solved?: string } | undefined;
  const pf = s.position_function as { primary_function?: string; function_mix_description?: string } | undefined;
  const dw = s.daily_workflow as { likely_analyses?: string[]; likely_outputs?: string[] } | undefined;
  const demands = s.underlying_skill_demands as { jd_phrase?: string; underlying_capability?: string; importance?: string }[] | undefined;
  const uncertaintyNotes = s.uncertainty_notes as { issue?: string; impact?: string }[] | undefined;
  const analystNotes = s.analyst_notes as string | undefined;
  const primaryCategory = s.primary_role_category as string | undefined;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <Badge className="bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)] text-xs">{report.status}</Badge>
        {report.used_research && (
          <Badge className="bg-[var(--match-good-bg)] text-[var(--match-good-fg)] text-xs">{t("withResearch")}</Badge>
        )}
        {primaryCategory && (
          <span className="text-sm font-medium" style={{ color: "oklch(36% 0.015 275)" }}>{primaryCategory}</span>
        )}
      </div>

      {bc?.summary && (
        <div>
          <SectionTitle>{t("businessContext")}</SectionTitle>
          <p className="text-[13px] leading-relaxed" style={{ color: "oklch(36% 0.01 275)" }}>{bc.summary}</p>
          {bc.problem_solved && (
            <p className="text-xs mt-2 leading-relaxed" style={{ color: "oklch(52% 0.01 275)" }}>
              {t("problemSolved", { text: bc.problem_solved })}
            </p>
          )}
        </div>
      )}

      {pf?.primary_function && (
        <div>
          <SectionTitle>{t("positionFunction")}</SectionTitle>
          <p className="text-sm font-medium" style={{ color: "oklch(22% 0.015 275)" }}>{pf.primary_function}</p>
          {pf.function_mix_description && (
            <p className="text-[13px] mt-1 leading-relaxed" style={{ color: "oklch(52% 0.01 275)" }}>{pf.function_mix_description}</p>
          )}
        </div>
      )}

      {dw && (dw.likely_analyses?.length || dw.likely_outputs?.length) ? (
        <div>
          <SectionTitle>{t("dailyWorkflow")}</SectionTitle>
          {dw.likely_analyses && dw.likely_analyses.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium mb-1.5" style={{ color: "oklch(50% 0.01 275)" }}>{t("typicalAnalyses")}</p>
              <BulletList items={dw.likely_analyses} />
            </div>
          )}
          {dw.likely_outputs && dw.likely_outputs.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-1.5" style={{ color: "oklch(50% 0.01 275)" }}>{t("outputs")}</p>
              <BulletList items={dw.likely_outputs} />
            </div>
          )}
        </div>
      ) : null}

      {demands && demands.length > 0 && (
        <div>
          <SectionTitle>{t("keySkillDemands")}</SectionTitle>
          <div className="space-y-2">
            {demands.map((d, i) => (
              <div key={i} className="flex gap-2.5 items-start text-[13px]">
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium mt-0.5 ${
                  d.importance === "core" ? "bg-rose-100 text-rose-700"
                  : d.importance === "supporting" ? "bg-amber-100 text-amber-700"
                  : "bg-[var(--match-partial-bg)] text-[var(--match-partial-fg)]"
                }`}>{d.importance ?? "—"}</span>
                <div>
                  <span className="font-medium" style={{ color: "oklch(30% 0.01 275)" }}>{d.jd_phrase}</span>
                  {d.underlying_capability && (
                    <span style={{ color: "oklch(52% 0.01 275)" }}> — {d.underlying_capability}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {analystNotes && (
        <div>
          <SectionTitle>{t("analystNotes")}</SectionTitle>
          <p className="text-[13px] leading-relaxed" style={{ color: "oklch(40% 0.01 275)" }}>{analystNotes}</p>
        </div>
      )}

      {uncertaintyNotes && uncertaintyNotes.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs font-semibold text-amber-700 mb-2">{t("uncertaintyNotes")}</p>
          <ul className="space-y-1.5">
            {uncertaintyNotes.map((n, i) => (
              <li key={i} className="text-[13px]">
                <span className="font-medium text-amber-700">{n.issue}</span>
                {n.impact && <span className="text-amber-600"> — {n.impact}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── Right: Fit Panel ── */

function FitPanel({ fitReport, job, profile }: { fitReport: FitReportResponse | null; job: JobRead; profile: ProfileRead | null }) {
  const t = useTranslations("jobDetail");

  if (!fitReport) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>{t("noFitAnalysis")}</p>
        <p className="text-xs mt-2" style={{ color: "oklch(60% 0.01 275)" }}>
          {t("noFitAnalysisHint")}
        </p>
      </div>
    );
  }

  return <FitReportTabs report={fitReport} job={job} profile={profile} />;
}

/* ── Main Component ── */

export function JobDetailTabs({ job, jd, jobReport, fitReport, profile, actions }: JobDetailTabsProps) {
  const t = useTranslations("jobDetail");
  const [rightTab, setRightTab] = useState<RightTab>("intelligence");

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Left: JD — independent scroll */}
      <div className="w-[45%] shrink-0 overflow-y-auto p-6" style={{ borderRight: "1px solid var(--border)" }}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold" style={{ color: "oklch(22% 0.015 275)" }}>{t("jobDescription")}</h2>
        </div>
        <JDPanel jd={jd} />
        <div className="h-8" />
      </div>

      {/* Right: Report tabs — independent scroll */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Tab bar + actions */}
        <div className="shrink-0 px-6 pt-4 pb-0 flex items-center justify-between gap-4" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setRightTab("intelligence")}
              className="px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors flex items-center gap-1.5"
              style={
                rightTab === "intelligence"
                  ? { borderColor: "var(--primary)", color: "var(--secondary-foreground)" }
                  : { borderColor: "transparent", color: "oklch(56% 0.01 275)" }
              }
            >
              {t("intelligenceReportTab")}
              {jobReport && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]">
                  {t("ready")}
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => setRightTab("fit")}
              className="px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors flex items-center gap-1.5"
              style={
                rightTab === "fit"
                  ? { borderColor: "var(--primary)", color: "var(--secondary-foreground)" }
                  : { borderColor: "transparent", color: "oklch(56% 0.01 275)" }
              }
            >
              {t("fitAnalysisTab")}
              {fitReport && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]">
                  {fitReport.overall_match_score}%
                </span>
              )}
            </button>
          </div>
          <div className="flex items-center gap-2 pb-1">
            {actions}
          </div>
        </div>

        {/* Tab content — scrollable */}
        <div className="flex-1 overflow-y-auto p-6">
          {rightTab === "intelligence" && <IntelligencePanel report={jobReport} />}
          {rightTab === "fit" && <FitPanel fitReport={fitReport} job={job} profile={profile} />}
          <div className="h-8" />
        </div>
      </div>
    </div>
  );
}
