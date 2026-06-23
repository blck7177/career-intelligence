interface DebugPanelProps {
  workspaceId: string;
  activeRunId?: string;
}

export function DebugPanel({ workspaceId, activeRunId }: DebugPanelProps) {
  return (
    <div className="p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-zinc-800">Debug</h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Inspect raw data and agent invocations.
        </p>
      </div>

      <div className="space-y-2 text-xs text-zinc-600">
        <div className="rounded border border-zinc-200 bg-zinc-50 px-3 py-2 space-y-1">
          <p className="font-medium text-zinc-500">Workspace</p>
          <p className="font-mono">{workspaceId}</p>
        </div>

        {activeRunId ? (
          <div className="rounded border border-zinc-200 bg-zinc-50 px-3 py-2 space-y-1">
            <p className="font-medium text-zinc-500">Active Run</p>
            <p className="font-mono break-all">{activeRunId}</p>
          </div>
        ) : (
          <div className="rounded border border-dashed border-zinc-300 px-3 py-2 text-zinc-400">
            No active run selected. Select a run from the Runs panel or start a new one.
          </div>
        )}

        <p className="text-zinc-400 pt-1">
          Switch to the right panel to view Agent Invocations and Raw JSON for the active run.
        </p>
      </div>
    </div>
  );
}
