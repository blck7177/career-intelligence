import { useState } from "react";
import type { RecentRun } from "./types";
import { RunDetail } from "./RunDetail";

interface Props {
  runs: RecentRun[];
}

function fmtCost(n: number): string {
  if (n === 0) return "-";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "-";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function badgeClass(status: string): string {
  return `badge badge-${status}`;
}

export function RecentRuns({ runs }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="card">
      <div className="card-header">Recent Runs</div>
      <table>
        <thead>
          <tr>
            <th>Run Type</th>
            <th>Status</th>
            <th className="num">LLM Calls</th>
            <th className="num">Tokens</th>
            <th className="num">Cost</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <>
              <tr
                key={r.id}
                className={`run-row ${expandedId === r.id ? "expanded" : ""}`}
                onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
              >
                <td className="run-type">{r.run_type}</td>
                <td><span className={badgeClass(r.status)}>{r.status}</span></td>
                <td className="num">{r.llm_calls || "-"}</td>
                <td className="num">{r.total_tokens ? r.total_tokens.toLocaleString() : "-"}</td>
                <td className={`num ${r.estimated_cost_usd > 0 ? "cost" : "cost-zero"}`}>
                  {fmtCost(r.estimated_cost_usd)}
                </td>
                <td className="time-ago">{timeAgo(r.created_at)}</td>
              </tr>
              {expandedId === r.id && <RunDetail key={`detail-${r.id}`} runId={r.id} />}
            </>
          ))}
          {runs.length === 0 && (
            <tr>
              <td colSpan={6} className="loading">No runs found</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
