import type { CostSummaryRow } from "./types";

interface Props {
  rows: CostSummaryRow[];
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function fmtCost(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function CostOverview({ rows }: Props) {
  const total = rows.reduce(
    (acc, r) => ({
      llm_calls: acc.llm_calls + r.llm_calls,
      prompt_tokens: acc.prompt_tokens + r.prompt_tokens,
      completion_tokens: acc.completion_tokens + r.completion_tokens,
      total_tokens: acc.total_tokens + r.total_tokens,
      estimated_cost_usd: acc.estimated_cost_usd + r.estimated_cost_usd,
    }),
    { llm_calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_cost_usd: 0 }
  );

  return (
    <div className="card">
      <div className="card-header">Cost by Run Type</div>
      <table>
        <thead>
          <tr>
            <th>Run Type</th>
            <th className="num">Calls</th>
            <th className="num">Tokens</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.run_type}>
              <td className="run-type">{r.run_type}</td>
              <td className="num">{fmt(r.llm_calls)}</td>
              <td className="num">{fmt(r.total_tokens)}</td>
              <td className="num cost">{fmtCost(r.estimated_cost_usd)}</td>
            </tr>
          ))}
          {rows.length > 0 && (
            <tr className="total-row">
              <td>Total</td>
              <td className="num">{fmt(total.llm_calls)}</td>
              <td className="num">{fmt(total.total_tokens)}</td>
              <td className="num">{fmtCost(total.estimated_cost_usd)}</td>
            </tr>
          )}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="loading">No usage data yet</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
