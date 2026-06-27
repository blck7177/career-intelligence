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
export type JDStructured = components["schemas"]["JDStructured"];
export type JobList = components["schemas"]["JobList"];
export type JobReportResponse = components["schemas"]["JobReportResponse"];
export type FitReportResponse = components["schemas"]["FitReportResponse"];
export type ProfileRead = components["schemas"]["ProfileRead"];
export type ProfileUpdate = components["schemas"]["ProfileUpdate"];
export type FitReportSummary = components["schemas"]["FitReportSummary"];
export type FitReportSummaryList = components["schemas"]["FitReportSummaryList"];

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

export async function listFitReports(
  params?: { profile_id?: string; status?: string },
  token?: string | null,
): Promise<FitReportSummaryList> {
  const qs = new URLSearchParams();
  if (params?.profile_id) qs.set("profile_id", params.profile_id);
  if (params?.status) qs.set("status", params.status);
  const query = qs.toString();
  return req<FitReportSummaryList>(
    `/api/app/fit-reports${query ? `?${query}` : ""}`,
    undefined,
    token,
  );
}

export async function getLatestJobReport(jobId: string, token?: string | null): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/app/jobs/${encodeURIComponent(jobId)}/job-reports/latest`, undefined, token);
}

// ---------------------------------------------------------------------------
// Jobs  (/api/app/jobs/*)
// ---------------------------------------------------------------------------

export async function listJobs(
  params?: { status?: string; include_report_summary?: boolean },
  token?: string | null,
): Promise<JobList> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.include_report_summary) qs.set("include_report_summary", "true");
  const query = qs.toString();
  return req<JobList>(`/api/app/jobs${query ? `?${query}` : ""}`, undefined, token);
}

export async function getJob(jobId: string, token?: string | null): Promise<JobRead> {
  return req<JobRead>(`/api/app/jobs/${encodeURIComponent(jobId)}`, undefined, token);
}

export async function archiveJob(jobId: string, token?: string | null): Promise<void> {
  await req<void>(`/api/app/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }, token);
}

// ---------------------------------------------------------------------------
// Profile  (/api/app/profile)
// ---------------------------------------------------------------------------
// ProfileRead / ProfileUpdate are exported from the generated types block above.

export async function getProfile(token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>("/api/app/profile", undefined, token);
}

export async function upsertProfile(body: ProfileUpdate, token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>("/api/app/profile", { method: "PUT", body: JSON.stringify(body) }, token);
}

export async function listProfiles(token?: string | null): Promise<ProfileRead[]> {
  return req<ProfileRead[]>("/api/app/profiles", undefined, token);
}

export async function createProfile(body: ProfileUpdate, token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>("/api/app/profiles", { method: "POST", body: JSON.stringify(body) }, token);
}

export async function updateProfile(profileId: string, body: ProfileUpdate, token?: string | null): Promise<ProfileRead> {
  return req<ProfileRead>(`/api/app/profiles/${encodeURIComponent(profileId)}`, { method: "PUT", body: JSON.stringify(body) }, token);
}

export async function deleteProfile(profileId: string, token?: string | null): Promise<void> {
  await req<void>(`/api/app/profiles/${encodeURIComponent(profileId)}`, { method: "DELETE" }, token);
}

export async function updateSearchDefaults(
  profileId: string,
  defaults: Record<string, unknown>,
  token?: string | null,
): Promise<void> {
  await req<void>(
    `/api/app/profiles/${encodeURIComponent(profileId)}/search-defaults`,
    { method: "PUT", body: JSON.stringify(defaults) },
    token,
  );
}

export async function uploadResume(
  file: File,
  token?: string | null,
): Promise<{ resume_text: string; char_count: number; source_filename: string }> {
  const resolvedToken = await resolveToken(token);
  const headers: Record<string, string> = {};
  if (resolvedToken) headers["Authorization"] = `Bearer ${resolvedToken}`;

  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE}/api/app/profile/upload-resume`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw Object.assign(new Error(text), { status: res.status });
  }
  return res.json();
}
