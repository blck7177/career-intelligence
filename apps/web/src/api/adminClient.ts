/**
 * Admin API client for Career OpenClaw — ops/developer endpoints.
 *
 * All endpoints under /api/admin/* require a user with is_admin=true.
 * Regular users calling these endpoints will receive a 403.
 *
 * Usage:
 *   import { adminListRuns, adminListTasks } from "@/api/adminClient";
 *   const runs = await adminListRuns(token);
 */

import type { components } from "@/api/generated/schema";

export type RunRead = components["schemas"]["RunRead"];
export type RunList = components["schemas"]["RunList"];
export type TaskRead = components["schemas"]["TaskRead"];
export type TaskEventRead = components["schemas"]["TaskEventRead"];
export type AgentInvocationRead = components["schemas"]["AgentInvocationRead"];

const BASE =
  typeof window !== "undefined"
    ? ""
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://api:8000");

async function req<T>(path: string, init?: RequestInit, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
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
// Admin Runs  (/api/admin/runs/*)
// ---------------------------------------------------------------------------

export async function adminListRuns(
  token: string | null,
  params?: { workspace_id?: string; status?: string; limit?: number },
): Promise<RunList> {
  const qs = new URLSearchParams();
  if (params?.workspace_id) qs.set("workspace_id", params.workspace_id);
  if (params?.status) qs.set("status", params.status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs}` : "";
  return req<RunList>(`/api/admin/runs${query}`, undefined, token);
}

export async function adminListTasks(runId: string, token: string | null): Promise<TaskRead[]> {
  return req<TaskRead[]>(`/api/admin/runs/${runId}/tasks`, undefined, token);
}

export async function adminListEvents(runId: string, token: string | null): Promise<TaskEventRead[]> {
  return req<TaskEventRead[]>(`/api/admin/runs/${runId}/events`, undefined, token);
}

export async function adminListAgentInvocations(
  runId: string,
  token: string | null,
): Promise<AgentInvocationRead[]> {
  return req<AgentInvocationRead[]>(`/api/admin/runs/${runId}/agent-invocations`, undefined, token);
}

export async function adminCancelRun(runId: string, token: string | null): Promise<RunRead> {
  return req<RunRead>(`/api/admin/runs/${runId}/cancel`, { method: "POST" }, token);
}

// ---------------------------------------------------------------------------
// Admin Users / Workspaces  (/api/admin/*)
// ---------------------------------------------------------------------------

export interface AdminUserRead {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
}

export interface AdminWorkspaceRead {
  id: string;
  name: string;
  created_at: string;
}

export async function adminListUsers(token: string | null): Promise<AdminUserRead[]> {
  return req<AdminUserRead[]>("/api/admin/users", undefined, token);
}

export async function adminListWorkspaces(token: string | null): Promise<AdminWorkspaceRead[]> {
  return req<AdminWorkspaceRead[]>("/api/admin/workspaces", undefined, token);
}
