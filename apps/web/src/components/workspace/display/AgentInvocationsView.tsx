"use client";

import { useState, useEffect } from "react";
import { listAgentInvocations } from "@/api/client";
import type { AgentInvocationRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { statusBg, fmtTs } from "@/lib/utils";
import { CheckCircle2, XCircle, Circle, AlertCircle } from "lucide-react";

interface AgentInvocationsViewProps {
  runId: string;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={13} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={13} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={13} className="text-blue-500 animate-pulse shrink-0" />;
  return <Circle size={13} className="text-zinc-300 shrink-0" />;
}

export function AgentInvocationsView({ runId }: AgentInvocationsViewProps) {
  const [invocations, setInvocations] = useState<AgentInvocationRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listAgentInvocations(runId)
      .then(setInvocations)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load invocations"),
      )
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading)
    return <p className="text-xs text-zinc-400 py-4 text-center">Loading agent invocations…</p>;
  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (invocations.length === 0)
    return (
      <p className="text-xs text-zinc-400 py-4 text-center">
        No agent invocations recorded for this run.
      </p>
    );

  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-400 border border-amber-200 bg-amber-50 text-amber-700 rounded px-3 py-1.5">
        Debug view — agent invocation data is not shown to end users.
      </p>
      <ul className="space-y-2">
        {invocations.map((inv) => {
          const dur =
            inv.started_at && inv.finished_at
              ? `${Math.round(
                  (new Date(inv.finished_at).getTime() - new Date(inv.started_at).getTime()) / 1000,
                )}s`
              : null;

          return (
            <li
              key={inv.id}
              className="flex items-start gap-2.5 rounded border border-zinc-100 px-3 py-2.5"
            >
              <StatusIcon status={inv.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-zinc-800">{inv.agent_id}</p>
                  <Badge className={statusBg(inv.status) + " text-[10px] shrink-0"}>
                    {inv.status}
                  </Badge>
                </div>
                <p className="text-xs text-zinc-500 mt-0.5">
                  {inv.skill_contract_version}
                  {dur && ` · ${dur}`}
                  {inv.exit_code != null && ` · exit ${inv.exit_code}`}
                  {inv.started_at && ` · started ${fmtTs(inv.started_at)}`}
                </p>
                {inv.error_code && (
                  <p className="text-xs text-rose-600 mt-0.5">
                    {inv.error_code}
                    {inv.error_message ? `: ${inv.error_message}` : ""}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
