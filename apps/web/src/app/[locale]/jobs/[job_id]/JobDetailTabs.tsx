"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileText, FileSearch, Target, Building2, Compass, Workflow, ListChecks, StickyNote } from "lucide-react";
import type { JobRead, JobReportResponse, FitReportResponse, JDStructured, ProfileRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { FitReportTabs } from "@/components/FitReportTabs";
import { bandOf, BAND } from "@/lib/matchBand";
import { EmptyState } from "@/components/EmptyState";
import { JobReportContent, type JobReportLabels } from "@/components/JobReportContent";

const JOB_REPORT_ICONS = {
  businessContext: Building2,
  positionFunction: Compass,
  dailyWorkflow: Workflow,
  skillDemands: ListChecks,
  analystNotes: StickyNote,
};

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
    <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--ink-muted)" }}>
      {children}
    </p>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
          <span className="shrink-0 mt-0.5" style={{ color: "var(--ink-faint)" }}>·</span>
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
    return <EmptyState icon={FileText} title={t("noJdData")} hint={t("noJdDataHint")} />;
  }

  const hasContent =
    jd.responsibilities.length > 0 ||
    jd.required_skills.length > 0 ||
    jd.preferred_skills.length > 0 ||
    jd.likely_tasks.length > 0;

  if (!hasContent) {
    return <EmptyState icon={FileSearch} title={t("noJdExtracted")} />;
  }

  return (
    <div className="space-y-6">
      {jd.inferred_team_context && (
        <div>
          <SectionTitle>{t("teamContext")}</SectionTitle>
          <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
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
    return <EmptyState icon={FileSearch} title={t("noIntelligenceReport")} hint={t("noIntelligenceReportHint")} />;
  }

  const labels: JobReportLabels = {
    businessContext: t("businessContext"),
    positionFunction: t("positionFunction"),
    dailyWorkflow: t("dailyWorkflow"),
    likelyInputs: t("likelyInputs"),
    typicalAnalyses: t("typicalAnalyses"),
    outputs: t("outputs"),
    keySkillDemands: t("keySkillDemands"),
    core: t("importanceCore"),
    supporting: t("importanceSupporting"),
    other: t("importanceOther"),
    analystNotes: t("analystNotes"),
    uncertaintyNotes: t("uncertaintyNotes"),
    confidence: t("confidenceLabel"),
    problemSolved: (text) => t("problemSolved", { text }),
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant="match-strong" className="text-xs">{report.status}</Badge>
        {report.used_research && (
          <Badge variant="match-good" className="text-xs">{t("withResearch")}</Badge>
        )}
      </div>
      <JobReportContent report={report} labels={labels} icons={JOB_REPORT_ICONS} />
    </div>
  );
}

/* ── Right: Fit Panel ── */

function FitPanel({ fitReport, job, profile }: { fitReport: FitReportResponse | null; job: JobRead; profile: ProfileRead | null }) {
  const t = useTranslations("jobDetail");

  if (!fitReport) {
    return <EmptyState icon={Target} title={t("noFitAnalysis")} hint={t("noFitAnalysisHint")} />;
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
          <h2 className="text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>{t("jobDescription")}</h2>
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
                  : { borderColor: "transparent", color: "var(--ink-muted)" }
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
                  : { borderColor: "transparent", color: "var(--ink-muted)" }
              }
            >
              {t("fitAnalysisTab")}
              {fitReport && (
                <span
                  className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    backgroundColor: BAND[bandOf(fitReport.overall_match_score)].bg,
                    color: BAND[bandOf(fitReport.overall_match_score)].fg,
                  }}
                >
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
          <div key={rightTab} className="animate-fade-in-up">
            {rightTab === "intelligence" && <IntelligencePanel report={jobReport} />}
            {rightTab === "fit" && <FitPanel fitReport={fitReport} job={job} profile={profile} />}
          </div>
          <div className="h-8" />
        </div>
      </div>
    </div>
  );
}
