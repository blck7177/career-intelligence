import { getRun } from "@/api/client";
import type { RunRead } from "@/api/client";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "needs_review"]);

export async function pollRunUntilDone(
  runId: string,
  token: string | null,
  options?: { intervalMs?: number; timeoutMs?: number },
): Promise<RunRead> {
  const intervalMs = options?.intervalMs ?? 3000;
  const timeoutMs = options?.timeoutMs ?? 600_000;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const run = await getRun(runId, token);
    if (TERMINAL.has(run.status)) return run;
    await new Promise((r) => setTimeout(r, intervalMs));
  }

  throw new Error("Run timed out — check Search Runs for status.");
}

export function extractReportId(run: RunRead): string | null {
  const summary = run.result_summary_json as Record<string, unknown> | null | undefined;
  const id = summary?.report_id;
  return typeof id === "string" ? id : null;
}
