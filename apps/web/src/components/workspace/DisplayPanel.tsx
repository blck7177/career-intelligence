"use client";

import { Inbox } from "lucide-react";
import type { RunRead } from "@/api/client";
import type { WorkspaceFunctionId, DisplayTab } from "@/lib/workspace/workspaceTypes";
import { ALL_DISPLAY_TABS } from "@/lib/workspace/workspaceTypes";
import { RunStatusView } from "./display/RunStatusView";
import { ReportView } from "./display/ReportView";
import { JobsView } from "./display/JobsView";
import { JobDetailView } from "./display/JobDetailView";
import { EmptyState } from "@/components/EmptyState";

interface DisplayPanelProps {
  activeFunction: WorkspaceFunctionId;
  activeRunId?: string;
  activeRun: RunRead | null;
  activeJobId?: string;
  activeDisplayTab: DisplayTab;
  visibleTabs: DisplayTab[];
  onTabChange: (tab: DisplayTab) => void;
  onRunCancelled: (updated: RunRead) => void;
  onJobSelected: (id: string) => void;
  onRunCreated: (runId: string) => void;
}

const NO_RUN_HINTS: Partial<Record<WorkspaceFunctionId, string>> = {
  discovery: "Fill in the parameters and start a discovery run.",
  job_report: "Enter a Job ID and generate a report.",
  fit_report: "Enter a Job ID and your profile, then generate a fit report.",
  runs: "Select a run from the list to inspect its details.",
};

export function DisplayPanel({
  activeFunction,
  activeRunId,
  activeRun,
  activeJobId,
  activeDisplayTab,
  visibleTabs,
  onTabChange,
  onRunCancelled,
  onJobSelected,
  onRunCreated,
}: DisplayPanelProps) {
  // Jobs function uses its own tab/content logic — no run required
  if (activeFunction === "jobs") {
    const tabMetas = ALL_DISPLAY_TABS.filter((t) => visibleTabs.includes(t.id));
    return (
      <div className="flex flex-col h-full">
        {/* Tab bar */}
        <div className="flex border-b border-[var(--border)] px-4 shrink-0">
          {tabMetas.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={[
                "px-3 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors",
                activeDisplayTab === tab.id
                  ? "border-[var(--primary)] text-[var(--secondary-foreground)] bg-[var(--secondary)]/40"
                  : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]",
              ].join(" ")}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div key={activeDisplayTab} className="animate-fade-in-up">
            {activeDisplayTab === "jobs" && (
              <JobsView
                activeJobId={activeJobId}
                onJobSelected={onJobSelected}
              />
            )}
            {activeDisplayTab === "job_detail" && activeJobId && (
              <JobDetailView
                jobId={activeJobId}
                onRunCreated={onRunCreated}
              />
            )}
            {activeDisplayTab === "job_detail" && !activeJobId && (
              <p className="text-xs text-[var(--ink-muted)] text-center py-8">
                Select a job from the list.
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (!activeRunId || !activeRun) {
    return (
      <div className="h-full flex items-center justify-center px-8">
        <EmptyState
          icon={Inbox}
          title="No run selected"
          hint={NO_RUN_HINTS[activeFunction] ?? "Select or start a run."}
          compact
        />
      </div>
    );
  }

  function renderContent() {
    switch (activeDisplayTab) {
      case "status":
        return <RunStatusView run={activeRun!} onCancelled={onRunCancelled} />;
      case "report":
        return <ReportView run={activeRun!} />;
      default:
        return null;
    }
  }

  const tabMetas = ALL_DISPLAY_TABS.filter((t) => visibleTabs.includes(t.id));

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex border-b border-[var(--border)] px-4 shrink-0">
        {tabMetas.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={[
              "px-3 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors",
              activeDisplayTab === tab.id
                ? "border-[var(--primary)] text-[var(--secondary-foreground)] bg-[var(--secondary)]/40"
                : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Run ID header */}
      <div className="px-4 py-2 border-b border-[var(--border)] bg-[var(--muted)]/60 shrink-0">
        <p className="text-[10px] font-mono text-[var(--ink-muted)] truncate">{activeRunId}</p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div key={activeDisplayTab} className="animate-fade-in-up">{renderContent()}</div>
      </div>
    </div>
  );
}
