import { useCallback, useEffect, useMemo, useState } from "react";
import type { CostSummaryRow, RecentRun, TimeRange, Workspace } from "./types";
import { CostOverview } from "./CostOverview";
import { RecentRuns } from "./RecentRuns";
import { WorkspaceFilter } from "./WorkspaceFilter";
import { TimeRangeFilter } from "./TimeRangeFilter";

function computeSince(range: TimeRange): string | undefined {
  if (range === "all") return undefined;
  const ms = { "24h": 86400000, "7d": 604800000, "30d": 2592000000 }[range];
  return new Date(Date.now() - ms).toISOString();
}

export function App() {
  const [costRows, setCostRows] = useState<CostSummaryRow[]>([]);
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("7d");

  useEffect(() => {
    fetch("/api/dashboard/workspaces")
      .then((r) => r.json())
      .then(setWorkspaces)
      .catch(() => {});
  }, []);

  const filterQs = useMemo(() => {
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    const since = computeSince(timeRange);
    if (since) params.set("since", since);
    return params.toString();
  }, [workspaceId, timeRange]);

  const refresh = useCallback(() => {
    setLoading(true);
    const suffix = filterQs ? `?${filterQs}` : "";
    const runsSuffix = filterQs ? `?limit=50&${filterQs}` : "?limit=50";
    Promise.all([
      fetch(`/api/dashboard/cost-summary${suffix}`).then((r) => r.json()),
      fetch(`/api/dashboard/recent-runs${runsSuffix}`).then((r) => r.json()),
    ])
      .then(([cost, recent]) => {
        setCostRows(cost);
        setRuns(recent);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [filterQs]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <>
      <header className="header">
        <h1>Career Intelligence Dev Console</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <WorkspaceFilter
            workspaces={workspaces}
            selected={workspaceId}
            onChange={setWorkspaceId}
          />
          <TimeRangeFilter selected={timeRange} onChange={setTimeRange} />
          <button className="refresh-btn" onClick={refresh} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <span className="version">v0.1</span>
        </div>
      </header>
      <div className="app-body">
        <div className="sidebar">
          <CostOverview rows={costRows} />
        </div>
        <div className="main">
          <RecentRuns runs={runs} filterQueryString={filterQs} />
        </div>
      </div>
    </>
  );
}
