"use client";

import type { WorkspaceFunctionId } from "@/lib/workspace/workspaceTypes";
import { DiscoveryPanel } from "./functions/DiscoveryPanel";
import { JobReportPanel } from "./functions/JobReportPanel";
import { FitReportPanel } from "./functions/FitReportPanel";
import { RunsPanel } from "./functions/RunsPanel";
import { JobsPanel } from "./functions/JobsPanel";

interface MiddlePanelProps {
  activeFunction: WorkspaceFunctionId;
  activeRunId?: string;
  activeJobId?: string;
  onRunCreated: (runId: string) => void;
  onSelectRun: (runId: string) => void;
  onJobSelected: (id: string) => void;
}

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

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto">{renderPanel()}</div>
    </div>
  );
}
