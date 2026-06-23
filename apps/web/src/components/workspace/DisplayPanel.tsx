"use client";

import type { RunRead } from "@/api/client";
import type { WorkspaceFunctionId, DisplayTab } from "@/lib/workspace/workspaceTypes";
import { ALL_DISPLAY_TABS } from "@/lib/workspace/workspaceTypes";
import { RunStatusView } from "./display/RunStatusView";
import { TasksView } from "./display/TasksView";
import { EventsView } from "./display/EventsView";
import { ReportView } from "./display/ReportView";
import { RawView } from "./display/RawView";
import { AgentInvocationsView } from "./display/AgentInvocationsView";

interface DisplayPanelProps {
  activeFunction: WorkspaceFunctionId;
  activeRunId?: string;
  activeRun: RunRead | null;
  activeDisplayTab: DisplayTab;
  visibleTabs: DisplayTab[];
  onTabChange: (tab: DisplayTab) => void;
  onRunCancelled: (updated: RunRead) => void;
}

function EmptyState({ activeFunction }: { activeFunction: WorkspaceFunctionId }) {
  const hints: Partial<Record<WorkspaceFunctionId, string>> = {
    discovery: "Fill in the parameters and start a discovery run.",
    job_report: "Enter a Job ID and generate a report.",
    fit_report: "Enter a Job ID and your profile, then generate a fit report.",
    runs: "Select a run from the list to inspect its details.",
    jobs: "Jobs list is coming soon.",
    debug: "Select a run to inspect debug data.",
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
  activeDisplayTab,
  visibleTabs,
  onTabChange,
  onRunCancelled,
}: DisplayPanelProps) {
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
      case "raw":
        return <RawView run={activeRun!} />;
      case "invocations":
        return <AgentInvocationsView runId={activeRunId!} />;
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
