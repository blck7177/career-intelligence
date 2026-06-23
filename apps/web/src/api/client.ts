/**
 * Typed API client for Career OpenClaw.
 *
 * All types are derived from the generated schema — do NOT hand-write types here.
 * Re-run `npm run gen:types` after any FastAPI route or Pydantic model change.
 *
 * Base URL:
 *   - Browser:  requests go through Next.js rewrites (/api/* → FastAPI)
 *   - SSR:      NEXT_PUBLIC_API_URL env var (or http://api:8000 in Docker)
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

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const BASE =
  typeof window !== "undefined"
    ? "" // Browser: use Next.js rewrites (same-origin)
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://api:8000");

// ---------------------------------------------------------------------------
// Request helper
// ---------------------------------------------------------------------------

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers as Record<string, string>) },
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

export async function createRun(body: RunCreate): Promise<RunRead> {
  return req<RunRead>("/api/runs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listRuns(workspaceId: string): Promise<RunList> {
  return req<RunList>(`/api/runs?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export async function getRun(runId: string): Promise<RunRead> {
  return req<RunRead>(`/api/runs/${runId}`);
}

export async function listTasks(runId: string): Promise<TaskRead[]> {
  return req<TaskRead[]>(`/api/runs/${runId}/tasks`);
}

export async function listEvents(runId: string): Promise<TaskEventRead[]> {
  return req<TaskEventRead[]>(`/api/runs/${runId}/events`);
}

export async function listAgentInvocations(runId: string): Promise<AgentInvocationRead[]> {
  return req<AgentInvocationRead[]>(`/api/runs/${runId}/agent-invocations`);
}

export async function cancelRun(runId: string): Promise<RunRead> {
  return req<RunRead>(`/api/runs/${runId}/cancel`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface JobReportResponse {
  id: string;
  job_id: string;
  status: string;
  jd_hash: string;
  prompt_version: string;
  used_research: boolean;
  research_bundle_hash?: string | null;
  structured_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  narrative_artifact_id?: string | null;
  structured_artifact_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FitReportResponse {
  id: string;
  workspace_id: string;
  job_id: string;
  job_report_id: string;
  candidate_profile_id?: string | null;
  overall_match_score: number;
  status: string;
  prompt_version: string;
  structured_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  narrative_artifact_id?: string | null;
  structured_artifact_id?: string | null;
  created_at: string;
  updated_at: string;
}

export async function getRunReport(
  runId: string
): Promise<JobReportResponse | FitReportResponse> {
  return req<JobReportResponse | FitReportResponse>(`/api/runs/${runId}/report`);
}

export async function getJobReport(jobReportId: string): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/job-reports/${jobReportId}`);
}

export async function getFitReport(fitReportId: string): Promise<FitReportResponse> {
  return req<FitReportResponse>(`/api/fit-reports/${fitReportId}`);
}

export async function getLatestJobReport(jobId: string): Promise<JobReportResponse> {
  return req<JobReportResponse>(`/api/jobs/${encodeURIComponent(jobId)}/job-reports/latest`);
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export async function listJobs(workspaceId: string): Promise<JobList> {
  return req<JobList>(`/api/jobs?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export async function getJob(jobId: string): Promise<JobRead> {
  return req<JobRead>(`/api/jobs/${encodeURIComponent(jobId)}`);
}
