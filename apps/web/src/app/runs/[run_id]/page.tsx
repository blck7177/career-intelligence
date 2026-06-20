import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun, listTasks, listEvents, listAgentInvocations } from "@/api/client";
import type { RunRead, TaskRead, TaskEventRead, AgentInvocationRead } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, CheckCircle2, XCircle, Circle, AlertCircle, Clock } from "lucide-react";
import { fmtTs, statusBg } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ run_id: string }>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={14} className="text-rose-500" />;
  if (status === "needs_review") return <AlertCircle size={14} className="text-amber-500" />;
  if (status === "running") return <Circle size={14} className="text-blue-500 animate-pulse" />;
  return <Circle size={14} className="text-zinc-400" />;
}

function TaskRow({ task }: { task: TaskRead }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-100 last:border-0">
      <div className="flex items-center gap-2">
        <StatusIcon status={task.status} />
        <div>
          <p className="text-xs font-medium">{task.task_type}</p>
          <p className="text-xs text-zinc-500">
            attempt {task.attempt_count}/{task.max_attempts}
            {task.started_at && ` · started ${fmtTs(task.started_at)}`}
          </p>
        </div>
      </div>
      <Badge className={statusBg(task.status) + " text-xs"}>{task.status}</Badge>
    </div>
  );
}

function EventRow({ event }: { event: TaskEventRead }) {
  return (
    <div className="flex gap-3 py-2 border-b border-zinc-100 last:border-0">
      <Clock size={12} className="text-zinc-400 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-xs font-medium text-zinc-700">{event.event_type}</p>
        {event.message && <p className="text-xs text-zinc-500 mt-0.5">{event.message}</p>}
        <p className="text-xs text-zinc-400 mt-0.5">{fmtTs(event.created_at)}</p>
      </div>
    </div>
  );
}

function AgentRow({ inv }: { inv: AgentInvocationRead }) {
  const dur =
    inv.started_at && inv.finished_at
      ? `${Math.round((new Date(inv.finished_at).getTime() - new Date(inv.started_at).getTime()) / 1000)}s`
      : null;

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-100 last:border-0">
      <div className="flex items-center gap-2">
        <StatusIcon status={inv.status} />
        <div>
          <p className="text-xs font-medium">{inv.agent_id}</p>
          <p className="text-xs text-zinc-500">
            {inv.skill_contract_version}
            {dur && ` · ${dur}`}
            {inv.exit_code != null && ` · exit ${inv.exit_code}`}
          </p>
        </div>
      </div>
      <Badge className={statusBg(inv.status) + " text-xs"}>{inv.status}</Badge>
    </div>
  );
}

export default async function RunDetailPage({ params }: PageProps) {
  const { run_id } = await params;

  let run: RunRead;
  try {
    run = await getRun(run_id);
  } catch {
    notFound();
  }

  const [tasks, events, invocations] = await Promise.all([
    listTasks(run_id).catch(() => [] as TaskRead[]),
    listEvents(run_id).catch(() => [] as TaskEventRead[]),
    listAgentInvocations(run_id).catch(() => [] as AgentInvocationRead[]),
  ]);

  return (
    <div className="space-y-6">
      {/* Back */}
      <Link
        href="/runs"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900"
      >
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold font-mono">{run_id}</h1>
          <p className="text-zinc-500 text-sm mt-1">
            {run.run_type.replace("_", " ")} · created {fmtTs(run.created_at)}
          </p>
        </div>
        <Badge className={statusBg(run.status) + " text-sm px-3 py-1"}>
          {run.status.replace("_", " ")}
        </Badge>
      </div>

      {run.error_message && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          <strong>{run.error_code}</strong>: {run.error_message}
        </div>
      )}

      {/* Three-column grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Tasks */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Tasks ({tasks.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {tasks.length === 0 ? (
              <p className="text-xs text-zinc-500">No tasks yet.</p>
            ) : (
              tasks.map((t) => <TaskRow key={t.id} task={t} />)
            )}
          </CardContent>
        </Card>

        {/* Events */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">Events ({events.length})</CardTitle>
          </CardHeader>
          <CardContent className="max-h-80 overflow-y-auto">
            {events.length === 0 ? (
              <p className="text-xs text-zinc-500">No events yet.</p>
            ) : (
              events.map((e) => <EventRow key={e.id} event={e} />)
            )}
          </CardContent>
        </Card>
      </div>

      {/* Agent Invocations */}
      {invocations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Agent Invocations ({invocations.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {invocations.map((inv) => (
              <AgentRow key={inv.id} inv={inv} />
            ))}
          </CardContent>
        </Card>
      )}

      {/* Raw JSON (dev only) */}
      <details className="text-xs">
        <summary className="cursor-pointer text-zinc-400 hover:text-zinc-600">
          Raw run data
        </summary>
        <pre className="mt-2 overflow-auto rounded-lg bg-zinc-50 p-4 text-zinc-600 max-h-64">
          {JSON.stringify(run, null, 2)}
        </pre>
      </details>
    </div>
  );
}
