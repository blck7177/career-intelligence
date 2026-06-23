/**
 * Typed API client for Career OpenClaw.
 *
 * All types are derived from the generated schema — do NOT hand-write types here.
 * Re-run `npm run gen:types` after any FastAPI route or Pydantic model change.
 *
 * Base URL:
 *   - Browser:  requests go through Next.js rewrites (/api/* → FastAPI)
 *   - SSR:      NEXT_PUBLIC_API_URL env var (or http://api:8000 in Docker)
 *
 * Auth:
 *   Every request includes the Clerk Bearer token obtained from useAuth().getToken().
 *   Server-side calls (SSR/RSC) use auth().getToken() from @clerk/nextjs/server.
 */

import type { components } from "@/api/generated/schema";

// ---------------------------------------------------------------------------
// Re-export generated types for use in pages/components
// ---------------------------------------------------------------------------

export type RunRead = components["schemas"]["RunRead"];
export type RunCreate = components["schemas"]["RunCreate"];
export type RunList = components["schemas"]["RunList"];
export type TaskRead = components["schemas"]["TaskRead"];
export type TaskEventRead = components["schemas"]["TaskEventRead"];
export type AgentInvocationRead = components["schemas"]["AgentInvocationRead"];
export type JobRead = components["schemas"]["JobRead"];
export type JobList = components["schemas"]["JobList"];
export type JobReportResponse = components["schemas"]["JobReportResponse"];
export type FitReportResponse = components["schemas"]["FitReportResponse"];

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const BASE =
  typeof window !== "undefined"
    ? "" // Browser: use Next.js rewrites (same-origin)
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://api:8000");

// ---------------------------------------------------------------------------
// Auth token resolver
// ---------------------------------------------------------------------------

/**
 * Retrieve the Clerk Bearer token for the current context.
 *
 * - Server Components / Route Handlers: import and call getServerToken() directly.
 * - Client Components: pass the token as a parameter to client functions,
 *   obtained via `const { getToken } = useAuth(); const t = await getToken();`
 *
 * The req() helper accepts an optional token parameter; when omitted it
 * attempts a server-side fetch via @clerk/nextjs/server.
 */
async function resolveToken(token?: string | null): Promise<string | null> {
  if (token !== undefined) return token;
  // Server-side: use Clerk server auth
  if (typeof window === "undefined") {
    try {
      const { auth } = await import("@clerk/nextjs/server");
      const { getToken } = await auth();
      return await getToken();
    } catch {
      return null;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Request helper
// ---------------------------------------------------------------------------

async function req<T>(path: string, init?: RequestInit, token?: string | null): Promise<T> {
  const resolvedToken = await resolveToken(token);
  const authHeader = resolvedToken ? { Authorization: `Bearer ${resolvedToken}` } : {};

  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeader,
      ...(init?.headers as Record<string, string>),
    },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw Object.assign(new Error(text), { status: res.status });
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export async function createRun(body: RunCreate, token?: string | null): Promise<RunRead> {
  return req<RunRead>("/api/runs", { method: "POST", body: JSON.stringify(body) }, token);
}

export async function listRuns(token?: string | null): Promise<RunList> {
  return req<RunList>("/api/runs", undefined, token);
}

export async function getRun(runId: string, token?: string | null): Promise<RunRead> {
  return req<RunRead>(`/api/runs/${runId}`, undefined, token);
}

export async function listTasks(runId: string, token?: string | null): Promise<TaskRead[]> {
  return req<TaskRead[]>(`/api/runs/${runId}/tasks`, undefined, token);
}

export async function listEvents(runId: string, token?: string | null): Promise<TaskEventRead[]> {
  return req<TaskEventRead[]>(`/api/runs/${runId}/events`, undefined, token);
}

export async function listAgentInvocations(runId: string, token?: string | null): Promise<AgentInvocationRead[]> {
  return req<AgentInvocationRead[]>(`/api/runs/${runId}/agent-invocations`, undefined, token);
}

export async function cancelRun(runId: string, token?: string | null): Promise<RunRead> {
  return req<RunRead>(`/api/runs/${runId}/cancel`, { method: "POST" }, token);
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export async function getRunReport(
  runId: string,
  token?: string | null,
): Promise<JobReportResponse | FitReportResponse> {
  return req<JobReportResponse | FitReportResponse>(`/api/runs/${runId}/report`, undefined, token);
}

export async function getJobReport(jobReportId: string, token?: string | null): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/job-reports/${jobReportId}`, undefined, token);
}

export async function getFitReport(fitReportId: string, token?: string | null): Promise<FitReportResponse> {
  return req<FitReportResponse>(`/api/fit-reports/${fitReportId}`, undefined, token);
}

export async function getLatestJobReport(jobId: string, token?: string | null): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/jobs/${encodeURIComponent(jobId)}/job-reports/latest`, undefined, token);
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export async function listJobs(token?: string | null): Promise<JobList> {
  return req<JobList>("/api/jobs", undefined, token);
}

export async function getJob(jobId: string, token?: string | null): Promise<JobRead> {
  return req<JobRead>(`/api/jobs/${encodeURIComponent(jobId)}`, undefined, token);
}
