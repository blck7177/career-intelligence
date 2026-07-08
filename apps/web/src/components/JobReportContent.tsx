import { Fragment, type ElementType } from "react";
import type { JobReportResponse } from "@/api/client";
import { BAND } from "@/lib/matchBand";

// ---------------------------------------------------------------------------
// Importance ramp — ONE hue (the app's own purple), darker = more emphasis.
// Deliberately NOT the red/amber status bands: "core vs supporting" is an
// emphasis ranking, not a good/bad signal, so it gets its own ordinal ramp.
// ---------------------------------------------------------------------------

const IMPORTANCE_STYLE: Record<string, { bg: string; fg: string }> = {
  core: { bg: "oklch(91% 0.05 285)", fg: "oklch(36% 0.16 285)" },
  supporting: { bg: "oklch(95.5% 0.028 285)", fg: "oklch(48% 0.11 285)" },
};
const IMPORTANCE_OTHER = { bg: "var(--muted)", fg: "var(--muted-foreground)" };

function importanceStyle(importance: string | undefined) {
  return (importance && IMPORTANCE_STYLE[importance]) || IMPORTANCE_OTHER;
}

type StructuredJson = {
  primary_role_category?: string;
  business_context?: { summary?: string; problem_solved?: string; confidence?: string };
  position_function?: { primary_function?: string; function_mix_description?: string; confidence?: string };
  daily_workflow?: { likely_inputs?: string[]; likely_analyses?: string[]; likely_outputs?: string[] };
  underlying_skill_demands?: { jd_phrase?: string; underlying_capability?: string; importance?: string }[];
  analyst_notes?: string;
  uncertainty_notes?: { issue?: string; impact?: string }[];
};

export interface JobReportLabels {
  businessContext: string;
  positionFunction: string;
  dailyWorkflow: string;
  likelyInputs: string;
  typicalAnalyses: string;
  outputs: string;
  keySkillDemands: string;
  core: string;
  supporting: string;
  other: string;
  analystNotes: string;
  uncertaintyNotes: string;
  confidence: string;
  problemSolved: (text: string) => string;
}

function IconChip({ icon: Icon }: { icon: ElementType }) {
  return (
    <span className="flex items-center justify-center w-6 h-6 rounded-full shrink-0 bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <Icon size={13} />
    </span>
  );
}

function SectionHeading({ icon, children }: { icon: ElementType; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold mb-2" style={{ color: "var(--ink-primary)" }}>
      <IconChip icon={icon} />
      {children}
    </div>
  );
}

function ConfidenceChip({ value, label }: { value: string | undefined; label: string }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium bg-[var(--muted)] text-[var(--ink-muted)] ml-2">
      {label}: {value}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Daily workflow — 3-stage pipeline. Renders only the stages with data, so a
// report missing "likely_inputs" still reads cleanly with 1-2 columns.
// ---------------------------------------------------------------------------

function WorkflowPipeline({
  inputs,
  analyses,
  outputs,
  labels,
}: {
  inputs?: string[];
  analyses?: string[];
  outputs?: string[];
  labels: JobReportLabels;
}) {
  const stages = [
    { key: "inputs", label: labels.likelyInputs, items: inputs },
    { key: "analyses", label: labels.typicalAnalyses, items: analyses },
    { key: "outputs", label: labels.outputs, items: outputs },
  ].filter((s) => s.items && s.items.length > 0);

  if (stages.length === 0) return null;

  return (
    <div className="flex items-stretch gap-2">
      {stages.map((stage, i) => (
        <Fragment key={stage.key}>
          <div className="flex-1 rounded-lg p-3 bg-[var(--muted)]">
            <h4 className="text-2xs font-bold uppercase tracking-wide mb-2 text-[var(--ink-muted)]">{stage.label}</h4>
            <ul className="space-y-1.5">
              {stage.items!.map((item, j) => (
                <li key={j} className="text-xs leading-snug pl-3 relative text-[var(--ink-secondary)]">
                  <span className="absolute left-0 top-[7px] w-[5px] h-[5px] rounded-full bg-[var(--primary)] opacity-50" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          {i < stages.length - 1 && (
            <div className="flex items-center text-[var(--ink-faint)] shrink-0">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill demands — composition bar (core/supporting/other counts) + list.
// ---------------------------------------------------------------------------

function SkillDemands({
  demands,
  labels,
}: {
  demands: { jd_phrase?: string; underlying_capability?: string; importance?: string }[];
  labels: JobReportLabels;
}) {
  const coreCount = demands.filter((d) => d.importance === "core").length;
  const supportingCount = demands.filter((d) => d.importance === "supporting").length;
  const otherCount = demands.length - coreCount - supportingCount;
  const total = demands.length;

  const segments = [
    { key: "core", count: coreCount, label: labels.core, color: IMPORTANCE_STYLE.core.fg },
    { key: "supporting", count: supportingCount, label: labels.supporting, color: IMPORTANCE_STYLE.supporting.fg },
    { key: "other", count: otherCount, label: labels.other, color: IMPORTANCE_OTHER.fg },
  ].filter((s) => s.count > 0);

  return (
    <div>
      {total > 1 && segments.length > 1 && (
        <div className="mb-3">
          <div className="flex h-2 w-full overflow-hidden rounded-full" style={{ background: IMPORTANCE_OTHER.bg }}>
            {segments.map((s, i) => (
              <div
                key={s.key}
                title={`${s.label}: ${s.count}`}
                style={{ width: `${(s.count / total) * 100}%`, backgroundColor: s.color, marginLeft: i === 0 ? 0 : 2 }}
                className="h-full first:rounded-l-full last:rounded-r-full"
              />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
            {segments.map((s) => (
              <div key={s.key} className="flex items-center gap-1.5 text-2xs text-[var(--ink-muted)]">
                <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                {s.label} <span className="font-semibold text-[var(--ink-secondary)]">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="space-y-1.5">
        {demands.map((d, i) => {
          const style = importanceStyle(d.importance);
          const importanceLabel =
            d.importance === "core" ? labels.core : d.importance === "supporting" ? labels.supporting : labels.other;
          return (
            <div key={i} className="flex gap-2.5 items-start rounded-md p-2 bg-[var(--muted)]/60">
              <span
                className="shrink-0 rounded px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wide mt-0.5"
                style={{ backgroundColor: style.bg, color: style.fg }}
              >
                {importanceLabel}
              </span>
              <div className="text-xs">
                <span className="font-medium" style={{ color: "var(--ink-secondary)" }}>{d.jd_phrase}</span>
                {d.underlying_capability && (
                  <span style={{ color: "var(--ink-muted)" }}> — {d.underlying_capability}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function JobReportContent({
  report,
  labels,
  icons,
}: {
  report: JobReportResponse;
  labels: JobReportLabels;
  icons: { businessContext: ElementType; positionFunction: ElementType; dailyWorkflow: ElementType; skillDemands: ElementType; analystNotes: ElementType };
}) {
  const s = report.structured_json as StructuredJson;
  const bc = s.business_context;
  const pf = s.position_function;
  const dw = s.daily_workflow;
  const demands = s.underlying_skill_demands;
  const uncertaintyNotes = s.uncertainty_notes;

  return (
    <div className="space-y-5">
      {s.primary_role_category && (
        <div
          className="inline-block text-sm font-semibold rounded-lg px-3 py-1.5"
          style={{ background: "var(--secondary)", color: "var(--secondary-foreground)" }}
        >
          {s.primary_role_category}
        </div>
      )}

      {bc?.summary && (
        <div>
          <SectionHeading icon={icons.businessContext}>
            {labels.businessContext}
            <ConfidenceChip value={bc.confidence} label={labels.confidence} />
          </SectionHeading>
          <p className="text-sm leading-relaxed" style={{ color: "var(--ink-secondary)" }}>{bc.summary}</p>
          {bc.problem_solved && (
            <p className="text-xs mt-1.5 leading-relaxed" style={{ color: "var(--ink-muted)" }}>
              {labels.problemSolved(bc.problem_solved)}
            </p>
          )}
        </div>
      )}

      {pf?.primary_function && (
        <div>
          <SectionHeading icon={icons.positionFunction}>
            {labels.positionFunction}
            <ConfidenceChip value={pf.confidence} label={labels.confidence} />
          </SectionHeading>
          <p className="text-sm font-medium" style={{ color: "var(--ink-primary)" }}>{pf.primary_function}</p>
          {pf.function_mix_description && (
            <p className="text-sm mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>{pf.function_mix_description}</p>
          )}
        </div>
      )}

      {dw && (dw.likely_inputs?.length || dw.likely_analyses?.length || dw.likely_outputs?.length) ? (
        <div>
          <SectionHeading icon={icons.dailyWorkflow}>{labels.dailyWorkflow}</SectionHeading>
          <WorkflowPipeline inputs={dw.likely_inputs} analyses={dw.likely_analyses} outputs={dw.likely_outputs} labels={labels} />
        </div>
      ) : null}

      {demands && demands.length > 0 && (
        <div>
          <SectionHeading icon={icons.skillDemands}>{labels.keySkillDemands}</SectionHeading>
          <SkillDemands demands={demands} labels={labels} />
        </div>
      )}

      {s.analyst_notes && (
        <div>
          <SectionHeading icon={icons.analystNotes}>{labels.analystNotes}</SectionHeading>
          <p className="text-sm leading-relaxed" style={{ color: "var(--ink-secondary)" }}>{s.analyst_notes}</p>
        </div>
      )}

      {uncertaintyNotes && uncertaintyNotes.length > 0 && (
        <div
          className="rounded-lg px-4 py-3"
          style={{ backgroundColor: BAND.partial.bg, border: `1px solid ${BAND.partial.border}` }}
        >
          <p className="text-xs font-semibold mb-1.5" style={{ color: BAND.partial.fg }}>{labels.uncertaintyNotes}</p>
          <ul className="space-y-1.5">
            {uncertaintyNotes.map((n, i) => (
              <li key={i} className="text-sm" style={{ color: BAND.partial.fg }}>
                <span className="font-medium">{n.issue}</span>
                {n.impact && <span className="opacity-80"> — {n.impact}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-2xs font-mono pt-1" style={{ color: "var(--ink-faint)" }}>
        {report.id} · v{report.prompt_version}
      </p>
    </div>
  );
}
