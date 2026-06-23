"use client";

import { useState, useEffect } from "react";
import { listTasks } from "@/api/client";
import type { TaskRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { statusBg, fmtTs } from "@/lib/utils";
import { CheckCircle2, XCircle, Circle, AlertCircle } from "lucide-react";

interface TasksViewProps {
  runId: string;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
  if (status === "failed") return <XCircle size={13} className="text-rose-500 shrink-0" />;
  if (status === "needs_review") return <AlertCircle size={13} className="text-amber-500 shrink-0" />;
  if (status === "running") return <Circle size={13} className="text-blue-500 animate-pulse shrink-0" />;
  return <Circle size={13} className="text-zinc-300 shrink-0" />;
}

export function TasksView({ runId }: TasksViewProps) {
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listTasks(runId)
      .then(setTasks)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tasks"))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <p className="text-xs text-zinc-400 py-4 text-center">Loading tasks…</p>;
  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (tasks.length === 0) return <p className="text-xs text-zinc-400 py-4 text-center">No tasks yet.</p>;

  return (
    <ul className="space-y-2">
      {tasks.map((task) => (
        <li
          key={task.id}
          className="flex items-start gap-2.5 rounded border border-zinc-100 px-3 py-2.5"
        >
          <StatusIcon status={task.status} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-zinc-800">{task.task_type}</p>
              <Badge className={statusBg(task.status) + " text-[10px] shrink-0"}>
                {task.status.replace("_", " ")}
              </Badge>
            </div>
            <p className="text-xs text-zinc-500 mt-0.5">
              attempt {task.attempt_count}/{task.max_attempts}
              {task.started_at && ` · started ${fmtTs(task.started_at)}`}
              {task.finished_at && ` · finished ${fmtTs(task.finished_at)}`}
            </p>
            {task.error_code && (
              <p className="text-xs text-rose-600 mt-0.5">
                {task.error_code}{task.error_message ? `: ${task.error_message}` : ""}
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
