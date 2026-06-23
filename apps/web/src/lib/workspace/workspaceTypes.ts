/**
 * Core types for the Workspace Shell.
 *
 * WorkspaceState is the single source of truth held by WorkspaceShell.tsx.
 * All child components receive slices of this state via props.
 */

// ---------------------------------------------------------------------------
// Function identifiers (left panel mode selector)
// ---------------------------------------------------------------------------

export type WorkspaceFunctionId =
  | "discovery"
  | "job_report"
  | "fit_report"
  | "runs"
  | "jobs";

export interface WorkspaceFunctionMeta {
  id: WorkspaceFunctionId;
  label: string;
  available: boolean;
  comingSoon?: boolean;
}

export const WORKSPACE_FUNCTIONS: WorkspaceFunctionMeta[] = [
  { id: "discovery", label: "Discovery", available: true },
  { id: "job_report", label: "Job Report", available: true },
  { id: "fit_report", label: "Fit Report", available: true },
  { id: "runs", label: "Runs", available: true },
  { id: "jobs", label: "Jobs", available: true },
];

// ---------------------------------------------------------------------------
// Display tabs (right panel)
// ---------------------------------------------------------------------------

export type DisplayTab =
  | "status"
  | "report"
  | "jobs"
  | "job_detail";

export interface DisplayTabMeta {
  id: DisplayTab;
  label: string;
}

export const ALL_DISPLAY_TABS: DisplayTabMeta[] = [
  { id: "status", label: "Status" },
  { id: "report", label: "Report" },
  { id: "jobs", label: "Jobs" },
  { id: "job_detail", label: "Job Detail" },
];

/**
 * Returns the tabs that are visible for a given function + run/job context.
 */
export function getVisibleTabs(
  activeFunction: WorkspaceFunctionId,
  runType?: string,
  runStatus?: string,
  activeJobId?: string,
): DisplayTab[] {
  if (activeFunction === "jobs") {
    const tabs: DisplayTab[] = ["jobs"];
    if (activeJobId) tabs.push("job_detail");
    return tabs;
  }

  const base: DisplayTab[] = ["status"];

  const isReportRun =
    runType === "job_report" || runType === "fit_report";
  const reportReady = isReportRun && runStatus === "succeeded";

  if (reportReady || activeFunction === "job_report" || activeFunction === "fit_report") {
    return [...base, "report"];
  }

  return base;
}

// ---------------------------------------------------------------------------
// Workspace state
// ---------------------------------------------------------------------------

export interface WorkspaceState {
  activeFunction: WorkspaceFunctionId;
  activeRunId?: string;
  activeJobId?: string;
  activeReportId?: string;
  activeDisplayTab: DisplayTab;
}

export const DEFAULT_WORKSPACE_STATE: WorkspaceState = {
  activeFunction: "discovery",
  activeRunId: undefined,
  activeJobId: undefined,
  activeReportId: undefined,
  activeDisplayTab: "status",
};

// ---------------------------------------------------------------------------
// Agent console (placeholder interface — for future use)
// ---------------------------------------------------------------------------

export interface AgentMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
}

export interface AgentConsoleProps {
  messages: AgentMessage[];
  disabled: boolean;
  placeholder?: string;
  onSend?: (message: string) => void;
}
