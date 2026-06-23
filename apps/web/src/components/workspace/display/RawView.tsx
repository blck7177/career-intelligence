import type { RunRead } from "@/api/client";

interface RawViewProps {
  run: RunRead;
}

export function RawView({ run }: RawViewProps) {
  return (
    <div className="space-y-3">
      <p className="text-xs font-medium text-zinc-500">Raw Run JSON</p>
      <pre className="overflow-auto rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-xs text-zinc-600 max-h-[500px]">
        {JSON.stringify(run, null, 2)}
      </pre>
    </div>
  );
}
