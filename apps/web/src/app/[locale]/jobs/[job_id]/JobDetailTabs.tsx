"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileText, FileSearch, Target, Building2, Compass, Workflow, ListChecks, StickyNote, Star, Users, Wrench } from "lucide-react";
import type { JobRead, JobReportResponse, FitReportResponse, JDStructured, ProfileRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { FitReportTabs } from "@/components/FitReportTabs";
import { bandOf, BAND } from "@/lib/matchBand";
import { EmptyState } from "@/components/EmptyState";
import { JobReportContent, SectionHeading, type JobReportLabels } from "@/components/JobReportContent";
import { TabsRoot, TabsList, Tab, TabsIndicator, TabsPanel } from "@/components/ui/tabs";
import { FitButton } from "@/components/FitButton";
import { ReportActionButton, TailorResumeButton, RemoveJobButton } from "./JobActions";
import { MarkAppliedButton } from "./MarkAppliedButton";

const JOB_REPORT_ICONS = {
  businessContext: Building2,
  positionFunction: Compass,
  dailyWorkflow: Workflow,
  skillDemands: ListChecks,
  analystNotes: StickyNote,
};

type PanelTab = "intelligence" | "fit" | "jd";

interface JobDetailTabsProps {
  job: JobRead;
  jd: JDStructured | null;
  jobReport: JobReportResponse | null;
  fitReport: FitReportResponse | null;
  profile: ProfileRead | null;
  hasExistingReport: boolean;
  jobReportId?: string;
  /** Called after a report/fit/resume action succeeds, in addition to
   * router.refresh() — only needed by the master-detail pane (JobDetailPane),
   * which fetches its own data client-side and never sees a bare
   * router.refresh(). The standalone /jobs/[id] page leaves this undefined
   * since it's a Server Component and router.refresh() alone is sufficient
   * there. */
  onMutated?: () => void;
  /** Whether to offer the actions that belong to the job library rather than
   *  to the posting — start tracking it, delete it. False when this pane is
   *  embedded somewhere the job is already tracked. */
  libraryActions?: boolean;
}

/* ── Shared ── */

/** columns=2 flows items into CSS multi-column layout (top-to-bottom then
 * next column — NOT a row-major grid, so reading order stays natural)
 * instead of one item per full-width line. Reserved for sections whose items
 * are reliably short phrases (skills) — sections with sentence-length,
 * variable items (responsibilities, tasks) default to columns=1 since long
 * items wrap unevenly next to short neighbors in a narrow column. */
function BulletList({ items, columns = 1 }: { items: string[]; columns?: 1 | 2 }) {
  if (!items.length) return null;
  return (
    <ul className={`space-y-1.5 ${columns === 2 ? "sm:columns-2 sm:gap-x-7" : ""}`}>
      {items.map((item, i) => (
        <li
          key={i}
          className="flex items-start gap-2 text-[15px] leading-relaxed break-inside-avoid"
          style={{ color: "var(--ink-secondary)" }}
        >
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

/** JDStructured has no "years required" field (that only exists on the
 * candidate's own ProfileRead) — pull it from the JD text itself so the
 * pinned strip can show it. Returns null (and the strip omits the fact)
 * rather than guessing, since a wrong number here could steer an application
 * decision. */
function extractYearsRequired(jd: JDStructured): string | null {
  const haystack = [...jd.required_skills, ...jd.responsibilities].join(". ");
  const match = haystack.match(/\d{1,2}\+?(?:\s*(?:-|–|to)\s*\d{1,2}\+?)?\s*years?/i);
  return match ? match[0].trim() : null;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <p className="text-[13px] leading-relaxed">
      <span className="font-bold uppercase tracking-wide text-2xs mr-2" style={{ color: "var(--ink-faint)" }}>
        {label}
      </span>
      <span style={{ color: "var(--ink-secondary)" }}>{value}</span>
    </p>
  );
}

/** Pinned under the title, above the three tabs — role-level facts that hold
 * true regardless of which tab is open, so they don't scroll away with the
 * JD body or get buried behind whichever tab happens to be active. Required
 * skills deliberately does NOT appear here — the JD tab's own Required
 * Skills row is the single source of truth for that list (this used to
 * duplicate it as a condensed, harder-to-scan sentence), and Intelligence/Fit
 * already surface skill relevance their own way (Key Skill Demands,
 * match breakdown). */
function BasicStrip({ jd }: { jd: JDStructured | null }) {
  const t = useTranslations("jobDetail");
  if (!jd) return null;

  const seniority = jd.seniority_inferred && jd.seniority_inferred !== "unknown" ? jd.seniority_inferred : null;
  const years = extractYearsRequired(jd);
  const team = jd.inferred_team_context || null;

  if (!seniority && !years && !team) return null;

  return (
    <div className="shrink-0 flex flex-col gap-2 px-6 py-3.5">
      {(seniority || years) && (
        <div className="flex items-baseline gap-7 flex-wrap">
          {seniority && <Fact label={t("seniorityLabel")} value={seniority} />}
          {years && <Fact label={t("experienceLabel")} value={years} />}
        </div>
      )}
      {team && <Fact label={t("teamContext")} value={team} />}
    </div>
  );
}

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

  // Team context surfaces once in the pinned BasicStrip above the tabs
  // instead of repeating here as its own section. Headings reuse Intelligence
  // Report's own SectionHeading/IconChip + space-y-5 rhythm (no dividers)
  // instead of a JD-only label-left grid, so switching tabs reads as the
  // same visual grammar rather than two different heading languages.
  return (
    <div className="space-y-5">
      {jd.responsibilities.length > 0 && (
        <div>
          <SectionHeading icon={Workflow}>{t("responsibilities")}</SectionHeading>
          <BulletList items={jd.responsibilities} columns={2} />
        </div>
      )}
      {jd.required_skills.length > 0 && (
        <div>
          <SectionHeading icon={ListChecks}>{t("requiredSkills")}</SectionHeading>
          <BulletList items={jd.required_skills} columns={2} />
        </div>
      )}
      {jd.preferred_skills.length > 0 && (
        <div>
          <SectionHeading icon={Star}>{t("preferredSkills")}</SectionHeading>
          <BulletList items={jd.preferred_skills} columns={2} />
        </div>
      )}
      {jd.likely_tasks.length > 0 && (
        <div>
          <SectionHeading icon={Compass}>{t("likelyTasks")}</SectionHeading>
          <BulletList items={jd.likely_tasks} />
        </div>
      )}
      {jd.likely_stakeholders.length > 0 && (
        <div>
          <SectionHeading icon={Users}>{t("stakeholders")}</SectionHeading>
          <TagList items={jd.likely_stakeholders} />
        </div>
      )}
      {jd.tools_mentioned.length > 0 && (
        <div>
          <SectionHeading icon={Wrench}>{t("toolsAndTech")}</SectionHeading>
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
      <div className="min-h-[50vh] flex items-center justify-center">
        <EmptyState icon={FileSearch} title={t("noIntelligenceReport")} hint={t("noIntelligenceReportHint")} />
      </div>
    );
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

function FitPanel({
  fitReport,
  job,
  profile,
  onMutated,
}: {
  fitReport: FitReportResponse | null;
  job: JobRead;
  profile: ProfileRead | null;
  onMutated?: () => void;
}) {
  const t = useTranslations("jobDetail");

  if (!fitReport) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <EmptyState icon={Target} title={t("noFitAnalysis")} hint={t("noFitAnalysisHint")} />
      </div>
    );
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
          <TailorResumeButton jobId={job.id} onMutated={onMutated} />
        </div>
      )}
      <FitReportTabs report={fitReport} job={job} profile={profile} />
    </div>
  );
}

/* ── Main Component ── */

export function JobDetailTabs({ job, jd, jobReport, fitReport, profile, hasExistingReport, jobReportId, onMutated, libraryActions = true }: JobDetailTabsProps) {
  const t = useTranslations("jobDetail");
  const tJobs = useTranslations("jobs");
  // Default to the first tab that actually has something to show — a job
  // with a fit score but no fresh report shouldn't open on an empty
  // Intelligence tab just because that's first in the list.
  const [tab, setTab] = useState<PanelTab>(() => (jobReport ? "intelligence" : fitReport ? "fit" : "jd"));

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      <BasicStrip jd={jd} />
      {/* Single-column panel (master-detail layout C): the AI-generated
          conclusion (Intelligence) leads, Fit follows, and the source JD —
          formerly a fixed right reference pane — is now the third tab. This
          keeps the panel one reading column at any width so it drops cleanly
          into the /jobs master-detail split without a nested horizontal
          split; the full-page /jobs/[id] fallback (<lg) reuses the same
          component, so both surfaces read identically. */}
      <TabsRoot value={tab} onValueChange={(v) => setTab(v as PanelTab)} className="flex-1 min-h-0 flex flex-col">
        {/* Tab bar + actions */}
        <div className="shrink-0 px-6 pt-4 pb-0 flex items-center justify-between gap-4" style={{ borderBottom: "1px solid var(--border)" }}>
          {/* Segmented-pill control: equal-width segments in a tinted
              container, active segment gets a solid elevated pill instead of
              a thin bottom underline. Every override lives here as
              className overrides on the shared Tab/TabsList/TabsIndicator
              primitives — FitReportTabs uses the same primitives with their
              default (underline) styling, so this doesn't change how tabs
              look anywhere else in the app. */}
          <TabsList className="border-b-0 bg-[var(--muted)] p-1 rounded-lg">
            <Tab value="intelligence" className="flex-1 justify-center flex items-center gap-1.5 rounded-md font-semibold">
              {t("intelligenceReportTab")}
              {jobReport && (
                <span className="px-1.5 py-0.5 rounded text-2xs font-medium min-w-[34px] text-center bg-[var(--match-strong-bg)] text-[var(--match-strong-fg)]">
                  {t("ready")}
                </span>
              )}
            </Tab>
            <Tab value="fit" className="flex-1 justify-center flex items-center gap-1.5 rounded-md font-semibold">
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
            <Tab value="jd" className="flex-1 flex items-center justify-center rounded-md font-semibold">
              {t("jobDescription")}
            </Tab>
            <TabsIndicator className="rounded-md bg-white border-b-0 shadow-sm" />
          </TabsList>
          {/* Only the action for the active tab shows here. The JD tab is
              pure reference (its "view original posting" affordance lives in
              the header), so it carries no primary action. Remove is
              page-level (not tab-scoped), so it always sits past a divider,
              de-emphasized. */}
          <div className="flex items-center gap-2.5 pb-1">
            {tab === "intelligence" && (
              <ReportActionButton jobId={job.id} hasExistingReport={hasExistingReport} onMutated={onMutated} />
            )}
            {tab === "fit" && (
              <FitButton
                jobId={job.id}
                jobReportId={jobReportId}
                disabled={!hasExistingReport}
                variant={hasExistingReport ? "default" : "outline"}
                label={tJobs("analyzeFit")}
                inline
                onMutated={onMutated}
              />
            )}
            {/* These two act on the job's place in the LIBRARY, not on the
                posting: one offers to start tracking it, the other deletes it
                and navigates to /jobs. Neither is right when this pane is
                being read from inside the tracker — the application already
                exists, and the navigation would take the day being planned
                with it. */}
            {libraryActions && (
              <>
                <MarkAppliedButton jobId={job.id} onMutated={onMutated} />
                <span className="w-px h-4 bg-[var(--border)]" />
                <RemoveJobButton jobId={job.id} />
              </>
            )}
          </div>
        </div>

        {/* Tab content — single scrollable reading column, symmetric gutters. */}
        <div className="flex-1 overflow-y-auto p-[var(--space-surface-spacious)]">
          <TabsPanel value="intelligence" className="animate-fade-in-up">
            <IntelligencePanel report={jobReport} />
          </TabsPanel>
          <TabsPanel value="fit" className="animate-fade-in-up">
            <FitPanel fitReport={fitReport} job={job} profile={profile} onMutated={onMutated} />
          </TabsPanel>
          <TabsPanel value="jd" className="animate-fade-in-up">
            <JDPanel jd={jd} />
          </TabsPanel>
          <div className="h-8" />
        </div>
      </TabsRoot>
    </div>
  );
}
