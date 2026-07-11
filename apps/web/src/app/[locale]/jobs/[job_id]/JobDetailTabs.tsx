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
import { TabsRoot, TabsList, Tab, TabsIndicator, TabsPanel } from "@/components/ui/tabs";
import { FitButton } from "@/components/FitButton";
import { ReportActionButton, TailorResumeButton, RemoveJobButton } from "./JobActions";

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
  hasExistingReport: boolean;
  jobReportId?: string;
}

/* ── Shared ── */

/** Bumped from text-xs/uppercase (12px, same tier as body meta) to a plain
 * bold sub-heading — was a full step smaller than the report's own section
 * headings for no real reason; now both panes use a comparable heading tier. */
function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-sm font-semibold mb-2" style={{ color: "var(--ink-primary)" }}>
      {children}
    </p>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-[15px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
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
        <span key={item} className="px-2.5 py-1 rounded-md text-xs font-medium" style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}>
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
          <p className="text-[15px] leading-relaxed" style={{ color: "var(--ink-secondary)" }}>
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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

  return (
    <div className="space-y-4">
      {/* Tailor Resume lives here now, not in the persistent toolbar — it's
          reacting to this score, so it belongs next to it. Gated on a fit
          report existing (not just hasExistingReport/job report) since
          "tailor for this role" only makes sense once there's a fit verdict
          to react to. */}
      {profile && (
        <div className="flex justify-end">
          <TailorResumeButton jobId={job.id} />
        </div>
      )}
      <FitReportTabs report={fitReport} job={job} profile={profile} />
    </div>
  );
}

/* ── Main Component ── */

export function JobDetailTabs({ job, jd, jobReport, fitReport, profile, hasExistingReport, jobReportId }: JobDetailTabsProps) {
  const t = useTranslations("jobDetail");
  const tJobs = useTranslations("jobs");
  const [rightTab, setRightTab] = useState<RightTab>("intelligence");

  return (
    <div className="flex flex-col lg:flex-row flex-1 min-h-0 overflow-hidden">
      {/* Left: Report tabs — the AI-generated conclusion is the primary
          view, so it takes the reading-priority position (independent
          scroll). JD moves to a secondary reference pane on the right —
          same pattern as evidence/citation panels in AI research products:
          the synthesized answer leads, the source material supports it. */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <TabsRoot value={rightTab} onValueChange={(v) => setRightTab(v as RightTab)} className="flex-1 min-h-0 flex flex-col">
          {/* Tab bar + actions */}
          <div className="shrink-0 px-6 pt-4 pb-0 flex items-center justify-between gap-4" style={{ borderBottom: "1px solid var(--border)" }}>
            <TabsList className="border-b-0">
              <Tab value="intelligence" className="flex items-center gap-1.5">
                {t("intelligenceReportTab")}
                {jobReport && (
                  <span className="px-1.5 py-0.5 rounded text-2xs font-medium min-w-[34px] text-center bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]">
                    {t("ready")}
                  </span>
                )}
              </Tab>
              <Tab value="fit" className="flex items-center gap-1.5">
                {t("fitAnalysisTab")}
                {fitReport && (
                  <span
                    className="px-1.5 py-0.5 rounded text-2xs font-medium min-w-[34px] text-center"
                    style={{
                      backgroundColor: BAND[bandOf(fitReport.overall_match_score)].bg,
                      color: BAND[bandOf(fitReport.overall_match_score)].fg,
                    }}
                  >
                    {fitReport.overall_match_score}%
                  </span>
                )}
              </Tab>
              <TabsIndicator />
            </TabsList>
            {/* Only the action for the active tab shows here — Refresh
                Report and Analyze Fit were both always visible regardless
                of which tab you were on, which made a static 4-button bar
                look like one homogeneous toolbar when really 2 of the 4
                only apply to one tab each. Remove is page-level (not
                tab-scoped), so it sits past a divider, de-emphasized. */}
            <div className="flex items-center gap-2.5 pb-1">
              {rightTab === "intelligence" && (
                <ReportActionButton jobId={job.id} hasExistingReport={hasExistingReport} />
              )}
              {rightTab === "fit" && (
                <FitButton
                  jobId={job.id}
                  jobReportId={jobReportId}
                  disabled={!hasExistingReport}
                  variant={hasExistingReport ? "default" : "outline"}
                  label={tJobs("analyzeFit")}
                  inline
                />
              )}
              <span className="w-px h-4 bg-[var(--border)]" />
              <RemoveJobButton jobId={job.id} />
            </div>
          </div>

          {/* Tab content — scrollable. Deliberately NOT width-capped: the
              JD pane on the right is its own fixed-ish column
              (min(--pane-reference-width),40%)), so letting this column
              fill the remaining flex-1 space keeps it flush against the
              JD pane instead of leaving a growing gap on wide screens
              (same fix as Home's main+rail layout). Left edge gets the same
              fixed --space-row-edge gutter as Home's main column at every
              width, instead of a max-width cap that would grow the margin
              on wide screens. */}
          <div className="flex-1 overflow-y-auto p-[var(--space-surface-spacious)] pl-[var(--space-row-edge)]">
            <TabsPanel value="intelligence" className="animate-fade-in-up">
              <IntelligencePanel report={jobReport} />
            </TabsPanel>
            <TabsPanel value="fit" className="animate-fade-in-up">
              <FitPanel fitReport={fitReport} job={job} profile={profile} />
            </TabsPanel>
            <div className="h-8" />
          </div>
        </TabsRoot>
      </div>

      {/* Right: JD — secondary reference pane (independent scroll), muted
          surface so it reads as supporting material rather than competing
          with the report for primary attention. Stacks below the report on
          narrow screens, same priority order as the desktop split. Width is
          capped at --pane-reference-width but never exceeds 40% of the row
          (min(...)), so this pane can't grow past the report's own width
          even at the lg breakpoint floor — a plain fixed px value would
          invert that priority right at 1024px, where the row is narrowest.
          Right edge gets the same fixed --space-row-edge gutter as Home's
          rail column at every width, instead of a max-width cap on the row
          as a whole. */}
      <div
        className="w-full lg:w-[min(var(--pane-reference-width),40%)] shrink-0 overflow-y-auto p-[var(--space-surface-spacious)] pr-[var(--space-row-edge)] max-h-[45vh] lg:max-h-none border-t lg:border-t-0 lg:border-l border-[var(--border)]"
        style={{ background: "var(--muted)" }}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>
            {t("jobDescription")}{" "}
            <span className="font-normal" style={{ color: "var(--ink-faint)" }}>({t("reference")})</span>
          </h2>
        </div>
        <JDPanel jd={jd} />
        <div className="h-8" />
      </div>
    </div>
  );
}
