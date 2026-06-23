"use client";

import type { RunRead } from "@/api/client";
import type { WorkspaceFunctionId, DisplayTab } from "@/lib/workspace/workspaceTypes";
import { ALL_DISPLAY_TABS } from "@/lib/workspace/workspaceTypes";
import { RunStatusView } from "./display/RunStatusView";
import { TasksView } from "./display/TasksView";
import { EventsView } from "./display/EventsView";
import { ReportView } from "./display/ReportView";
import { JobsView } from "./display/JobsView";
import { JobDetailView } from "./display/JobDetailView";

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

function EmptyState({ activeFunction }: { activeFunction: WorkspaceFunctionId }) {
  const hints: Partial<Record<WorkspaceFunctionId, string>> = {
    discovery: "Fill in the parameters and start a discovery run.",
    job_report: "Enter a Job ID and generate a report.",
    fit_report: "Enter a Job ID and your profile, then generate a fit report.",
    runs: "Select a run from the list to inspect its details.",
  };

  return (
    <div className="flex flex-col items-center justify-center h-64 gap-2 text-center px-8">
      <div className="w-8 h-8 rounded-full bg-zinc-100 flex items-center justify-center">
        <span className="text-zinc-400 text-xs">—</span>
      </div>
      <p className="text-sm text-zinc-500 font-medium">No run selected</p>
      <p className="text-xs text-zinc-400">{hints[activeFunction] ?? "Select or start a run."}</p>
    </div>
  );
}

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
        <div className="flex border-b border-zinc-200 px-4 shrink-0">
          {tabMetas.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={[
                "px-3 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors",
                activeDisplayTab === tab.id
                  ? "border-zinc-800 text-zinc-800"
                  : "border-transparent text-zinc-400 hover:text-zinc-600",
              ].join(" ")}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-4">
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
            <p className="text-xs text-zinc-400 text-center py-8">
              Select a job from the list.
            </p>
          )}
        </div>
      </div>
    );
  }

  if (!activeRunId || !activeRun) {
    return (
      <div className="h-full">
        <EmptyState activeFunction={activeFunction} />
      </div>
    );
  }

  function renderContent() {
    switch (activeDisplayTab) {
      case "status":
        return <RunStatusView run={activeRun!} onCancelled={onRunCancelled} />;
      case "tasks":
        return <TasksView runId={activeRunId!} />;
      case "events":
        return <EventsView runId={activeRunId!} />;
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
      <div className="flex border-b border-zinc-200 px-4 shrink-0">
        {tabMetas.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={[
              "px-3 py-2.5 text-xs font-medium border-b-2 -mb-px transition-colors",
              activeDisplayTab === tab.id
                ? "border-zinc-800 text-zinc-800"
                : "border-transparent text-zinc-400 hover:text-zinc-600",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Run ID header */}
      <div className="px-4 py-2 border-b border-zinc-100 bg-zinc-50/60 shrink-0">
        <p className="text-[10px] font-mono text-zinc-400 truncate">{activeRunId}</p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">{renderContent()}</div>
    </div>
  );
}
