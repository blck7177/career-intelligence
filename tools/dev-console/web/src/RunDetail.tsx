import { useEffect, useState } from "react";
import type { RunError, UsageEvent } from "./types";
import { authFetch } from "./auth";

interface Props {
  runId: string;
  filterQueryString: string;
}

function fmtCost(n: number | null): string {
  if (n === null || n === 0) return "-";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function groupErrorsByTask(errors: RunError[]): Map<string, RunError[]> {
  const map = new Map<string, RunError[]>();
  for (const e of errors) {
    const group = map.get(e.task_id) ?? [];
    group.push(e);
    map.set(e.task_id, group);
  }
  return map;
}

export function RunDetail({ runId, filterQueryString }: Props) {
  const [events, setEvents] = useState<UsageEvent[]>([]);
  const [errors, setErrors] = useState<RunError[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const qs = filterQueryString ? `?${filterQueryString}` : "";
    Promise.all([
      authFetch(`/api/dashboard/runs/${runId}/usage${qs}`).then((r) => r.json()),
      authFetch(`/api/dashboard/runs/${runId}/errors`).then((r) => r.json()),
    ])
      .then(([usageData, errorData]) => {
        setEvents(usageData);
        setErrors(errorData);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [runId, filterQueryString]);

  if (loading) return <tr className="run-detail"><td colSpan={6} className="loading">Loading...</td></tr>;
  if (events.length === 0 && errors.length === 0) {
    return <tr className="run-detail"><td colSpan={6} className="loading">No LLM calls recorded</td></tr>;
  }

  return (
    <>
      {errors.length > 0 && (
        <tr className="run-detail">
          <td colSpan={6} style={{ padding: 0 }}>
            <div className="error-section">
              <div className="error-section-header">Errors</div>
              {[...groupErrorsByTask(errors)].map(([taskId, taskErrors]) => (
                <div key={taskId} className="error-task-group">
                  <div className="error-task-header">
                    <span className="run-type">{taskErrors[0].task_type}</span>
                    <span className={`badge badge-${taskErrors[0].task_status}`}>
                      {taskErrors[0].task_status}
                    </span>
                    {taskErrors[0].task_error_code && (
                      <span className="error-code">{taskErrors[0].task_error_code}</span>
                    )}
                    <span className="error-attempts">
                      {taskErrors[0].attempt_count} attempt(s)
                    </span>
                  </div>
                  {taskErrors[0].task_error_message && (
                    <div className="error-message">{taskErrors[0].task_error_message}</div>
                  )}
                  {taskErrors
                    .filter((e) => e.invocation_id)
                    .map((e) => (
                      <div key={e.invocation_id} className="error-agent">
                        <span className="error-agent-id">{e.agent_id}</span>
                        {e.exit_code !== null && e.exit_code !== 0 && (
                          <span className="error-exit-code">exit {e.exit_code}</span>
                        )}
                        {e.agent_error_code && (
                          <span className="error-code">{e.agent_error_code}</span>
                        )}
                        {e.agent_error_message && (
                          <div className="error-message">{e.agent_error_message}</div>
                        )}
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
      {events.length > 0 && (
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
      )}
    </>
  );
}
