"use client";

import type { WorkspaceFunctionId } from "@/lib/workspace/workspaceTypes";
import { DiscoveryPanel } from "./functions/DiscoveryPanel";
import { JobReportPanel } from "./functions/JobReportPanel";
import { FitReportPanel } from "./functions/FitReportPanel";
import { RunsPanel } from "./functions/RunsPanel";
import { JobsPanel } from "./functions/JobsPanel";
import { AgentConsolePlaceholder } from "./AgentConsolePlaceholder";
import type { AgentMessage } from "@/lib/workspace/workspaceTypes";

interface MiddlePanelProps {
  activeFunction: WorkspaceFunctionId;
  activeRunId?: string;
  activeJobId?: string;
  onRunCreated: (runId: string) => void;
  onSelectRun: (runId: string) => void;
  onJobSelected: (id: string) => void;
}

const SYSTEM_PLACEHOLDER: AgentMessage = {
  id: "sys-0",
  role: "system",
  content: "Agent console is not enabled yet. Use the parameter panel above to run workflows.",
  createdAt: new Date().toISOString(),
};

export function MiddlePanel({
  activeFunction,
  activeRunId,
  activeJobId,
  onRunCreated,
  onSelectRun,
  onJobSelected,
}: MiddlePanelProps) {
  function renderPanel() {
    switch (activeFunction) {
      case "discovery":
        return <DiscoveryPanel onRunCreated={onRunCreated} />;
      case "job_report":
        return <JobReportPanel onRunCreated={onRunCreated} />;
      case "fit_report":
        return <FitReportPanel onRunCreated={onRunCreated} />;
      case "runs":
        return <RunsPanel activeRunId={activeRunId} onSelectRun={onSelectRun} />;
      case "jobs":
        return <JobsPanel activeJobId={activeJobId} onJobSelected={onJobSelected} />;
      default:
        return null;
    }
  }

  // Only show agent console for action-triggering modes (not Runs/Jobs/Debug list views)
  const showAgentConsole = ["discovery", "job_report", "fit_report"].includes(activeFunction);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto">{renderPanel()}</div>
      {showAgentConsole && (
        <AgentConsolePlaceholder
          messages={[SYSTEM_PLACEHOLDER]}
          disabled={true}
          placeholder="Agent chat coming soon…"
        />
      )}
    </div>
  );
}
