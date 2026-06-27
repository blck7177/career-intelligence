import { useEffect, useState } from "react";
import type { UsageEvent } from "./types";

interface Props {
  runId: string;
}

function fmtCost(n: number | null): string {
  if (n === null || n === 0) return "-";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function RunDetail({ runId }: Props) {
  const [events, setEvents] = useState<UsageEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/dashboard/runs/${runId}/usage`)
      .then((r) => r.json())
      .then((data) => { setEvents(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [runId]);

  if (loading) return <tr className="run-detail"><td colSpan={6} className="loading">Loading...</td></tr>;
  if (events.length === 0) return <tr className="run-detail"><td colSpan={6} className="loading">No LLM calls recorded</td></tr>;

  return (
    <>
      <tr className="run-detail">
        <td colSpan={6} style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Call Site</th>
                <th>Model</th>
                <th className="num">Prompt</th>
                <th className="num">Completion</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="run-type">{e.call_site}</td>
                  <td style={{ fontSize: 12, color: "var(--muted)" }}>{e.model}</td>
                  <td className="num">{e.prompt_tokens.toLocaleString()}</td>
                  <td className="num">{e.completion_tokens.toLocaleString()}</td>
                  <td className="num cost">{fmtCost(e.estimated_cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </td>
      </tr>
    </>
  );
}
