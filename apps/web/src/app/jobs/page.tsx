/**
 * Jobs page — Phase 2 stub.
 *
 * The jobs table will be populated once Phase 3 (worker) and Phase 4 (agent)
 * are complete. For now this page shows a placeholder.
 *
 * The API endpoint GET /api/jobs will be added in Phase 2 follow-up or Phase 3.
 */

export const dynamic = "force-dynamic";

export default function JobsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Discovered Jobs</h1>
        <p className="text-zinc-500 text-sm mt-1">
          Jobs appear here after a discovery run completes and passes validation.
        </p>
      </div>

      <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-12 text-center">
        <p className="text-zinc-500 text-sm">
          No jobs yet. Run a discovery run to find and ingest jobs.
        </p>
        <p className="text-zinc-400 text-xs mt-2">
          Jobs API endpoint: <code className="font-mono">GET /api/jobs</code> (Phase 3)
        </p>
      </div>
    </div>
  );
}
