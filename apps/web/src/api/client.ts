/**
 * Typed API client for Career OpenClaw — product (user-facing) endpoints.
 *
 * All types are derived from the generated schema — do NOT hand-write types here.
 * Re-run `npm run gen:types` after any FastAPI route or Pydantic model change.
 *
 * Base URL:
 *   - Browser:  requests go through Next.js rewrites (/api/* → FastAPI)
 *   - SSR:      NEXT_PUBLIC_API_URL env var (or http://api:8000 in Docker)
 *
 * Auth:
 *   Every request includes the Bearer token obtained from useApiToken()().
 *   Server-side calls (SSR/RSC) use auth().getToken() from @clerk/nextjs/server.
 *
 * Route prefix:
 *   All product endpoints live under /api/app/*.
 *   Admin/debug endpoints are in adminClient.ts under /api/admin/*.
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
 * Resolve the bearer token for an API call.
 *
 * - Server Components / Route Handlers: call getServerToken() from
 *   @/lib/server-auth and pass the result explicitly.
 * - Client Components: pass the token obtained via useApiToken().
 *
 * This function intentionally does NOT import @clerk/nextjs/server so that
 * client.ts remains safe to import from "use client" modules.
 */
async function resolveToken(token?: string | null): Promise<string | null> {
  if (token !== undefined) return token;
  return null;
}

// ---------------------------------------------------------------------------
// Request helper
// ---------------------------------------------------------------------------

async function req<T>(path: string, init?: RequestInit, token?: string | null): Promise<T> {
  const resolvedToken = await resolveToken(token);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (resolvedToken) headers["Authorization"] = `Bearer ${resolvedToken}`;

  const res = await fetch(`${BASE}${path}`, {
    headers: {
      ...headers,
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
// Runs  (/api/app/runs/*)
// ---------------------------------------------------------------------------

export async function createRun(body: RunCreate, token?: string | null): Promise<RunRead> {
  return req<RunRead>("/api/app/runs", { method: "POST", body: JSON.stringify(body) }, token);
}

export async function listRuns(token?: string | null): Promise<RunList> {
  return req<RunList>("/api/app/runs", undefined, token);
}

export async function getRun(runId: string, token?: string | null): Promise<RunRead> {
  return req<RunRead>(`/api/app/runs/${runId}`, undefined, token);
}

export async function cancelRun(runId: string, token?: string | null): Promise<RunRead> {
  return req<RunRead>(`/api/app/runs/${runId}/cancel`, { method: "POST" }, token);
}

// ---------------------------------------------------------------------------
// Reports  (/api/app/*)
// ---------------------------------------------------------------------------

export async function getRunReport(
  runId: string,
  token?: string | null,
): Promise<JobReportResponse | FitReportResponse> {
  return req<JobReportResponse | FitReportResponse>(`/api/app/runs/${runId}/report`, undefined, token);
}

export async function getJobReport(jobReportId: string, token?: string | null): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/app/job-reports/${jobReportId}`, undefined, token);
}

export async function getFitReport(fitReportId: string, token?: string | null): Promise<FitReportResponse> {
  return req<FitReportResponse>(`/api/app/fit-reports/${fitReportId}`, undefined, token);
}

export async function getLatestJobReport(jobId: string, token?: string | null): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/app/jobs/${encodeURIComponent(jobId)}/job-reports/latest`, undefined, token);
}

// ---------------------------------------------------------------------------
// Jobs  (/api/app/jobs/*)
// ---------------------------------------------------------------------------

export async function listJobs(token?: string | null): Promise<JobList> {
  return req<JobList>("/api/app/jobs", undefined, token);
}

export async function getJob(jobId: string, token?: string | null): Promise<JobRead> {
  return req<JobRead>(`/api/app/jobs/${encodeURIComponent(jobId)}`, undefined, token);
}

// ---------------------------------------------------------------------------
// Profile  (/api/app/profile)
// ---------------------------------------------------------------------------
// Types are generated from OpenAPI spec — do NOT hand-write these.

export type ProfileRead = components["schemas"]["ProfileRead"];
export type ProfileUpdate = components["schemas"]["ProfileUpdate"];

export async function getProfile(token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>("/api/app/profile", undefined, token);
}

export async function upsertProfile(body: ProfileUpdate, token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>("/api/app/profile", { method: "PUT", body: JSON.stringify(body) }, token);
}
