"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { getRun } from "@/api/client";
import type { RunRead } from "@/api/client";
import {
  DEFAULT_WORKSPACE_STATE,
  getVisibleTabs,
} from "@/lib/workspace/workspaceTypes";
import type { WorkspaceState, WorkspaceFunctionId, DisplayTab } from "@/lib/workspace/workspaceTypes";
import { FunctionPanel } from "./FunctionPanel";
import { MiddlePanel } from "./MiddlePanel";
import { DisplayPanel } from "./DisplayPanel";

const POLL_INTERVAL_MS = 3000;

export function WorkspaceShell() {
  const getToken = useApiToken();
  const [state, setState] = useState<WorkspaceState>(DEFAULT_WORKSPACE_STATE);
  const [activeRun, setActiveRun] = useState<RunRead | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Polling: refresh activeRun while it's in a non-terminal status
  // ---------------------------------------------------------------------------

  const fetchRun = useCallback(async (runId: string) => {
    try {
      const token = await getToken();
      const run = await getRun(runId, token);
      setActiveRun(run);
      return run;
    } catch {
      return null;
    }
  }, [getToken]);

  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    if (!state.activeRunId) {
      setActiveRun(null);
      return;
    }

    // Immediate fetch
    fetchRun(state.activeRunId).then((run) => {
      if (run && (run.status === "queued" || run.status === "running")) {
        pollRef.current = setInterval(() => {
          fetchRun(state.activeRunId!).then((updated) => {
            if (
              updated &&
              updated.status !== "queued" &&
              updated.status !== "running"
            ) {
              if (pollRef.current) {
                clearInterval(pollRef.current);
                pollRef.current = null;
              }
            }
          });
        }, POLL_INTERVAL_MS);
      }
    });

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [state.activeRunId, fetchRun]);

  // ---------------------------------------------------------------------------
  // State mutation helpers
  // ---------------------------------------------------------------------------

  const setActiveFunction = useCallback((fn: WorkspaceFunctionId) => {
    setState((prev) => ({
      ...prev,
      activeFunction: fn,
      activeDisplayTab: "status",
    }));
  }, []);

  const setActiveRunId = useCallback((runId: string) => {
    setState((prev) => ({
      ...prev,
      activeRunId: runId,
      activeDisplayTab: "status",
    }));
  }, []);

  const setActiveDisplayTab = useCallback((tab: DisplayTab) => {
    setState((prev) => ({ ...prev, activeDisplayTab: tab }));
  }, []);

  const handleRunCreated = useCallback(
    (runId: string) => {
      setActiveRunId(runId);
    },
    [setActiveRunId],
  );

  const handleRunCancelled = useCallback((updatedRun: RunRead) => {
    setActiveRun(updatedRun);
  }, []);

  const handleJobSelected = useCallback((jobId: string) => {
    setState((prev) => ({
      ...prev,
      activeJobId: jobId,
      activeDisplayTab: "job_detail",
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Derived: visible tabs based on current function + run/job state
  // ---------------------------------------------------------------------------

  const visibleTabs = getVisibleTabs(
    state.activeFunction,
    activeRun?.run_type,
    activeRun?.status,
    state.activeJobId,
  );

  // Reset tab if current tab is no longer visible
  const safeDisplayTab = visibleTabs.includes(state.activeDisplayTab)
    ? state.activeDisplayTab
    : visibleTabs[0] ?? "status";

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* Left: Function selector — 240px fixed */}
      <div className="w-60 shrink-0 border-r border-zinc-200 bg-zinc-50 overflow-y-auto">
        <FunctionPanel
          activeFunction={state.activeFunction}
          onSelect={setActiveFunction}
        />
      </div>

      {/* Middle: Parameter panel + agent placeholder — 420px fixed */}
      <div className="w-[420px] shrink-0 border-r border-zinc-200 overflow-y-auto">
        <MiddlePanel
          activeFunction={state.activeFunction}
          activeRunId={state.activeRunId}
          activeJobId={state.activeJobId}
          onRunCreated={handleRunCreated}
          onSelectRun={setActiveRunId}
          onJobSelected={handleJobSelected}
        />
      </div>

      {/* Right: Display panel — flex-1 */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <DisplayPanel
          activeFunction={state.activeFunction}
          activeRunId={state.activeRunId}
          activeRun={activeRun}
          activeJobId={state.activeJobId}
          activeDisplayTab={safeDisplayTab}
          visibleTabs={visibleTabs}
          onTabChange={setActiveDisplayTab}
          onRunCancelled={handleRunCancelled}
          onJobSelected={handleJobSelected}
          onRunCreated={handleRunCreated}
        />
      </div>
    </div>
  );
}
