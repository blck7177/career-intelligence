import { useCallback, useEffect, useState } from "react";
import type { CostSummaryRow, RecentRun } from "./types";
import { CostOverview } from "./CostOverview";
import { RecentRuns } from "./RecentRuns";

export function App() {
  const [costRows, setCostRows] = useState<CostSummaryRow[]>([]);
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetch("/api/dashboard/cost-summary").then((r) => r.json()),
      fetch("/api/dashboard/recent-runs?limit=50").then((r) => r.json()),
    ])
      .then(([cost, recent]) => {
        setCostRows(cost);
        setRuns(recent);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <>
      <header className="header">
        <h1>Career Intelligence Dev Console</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
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
          <RecentRuns runs={runs} />
        </div>
      </div>
    </>
  );
}
