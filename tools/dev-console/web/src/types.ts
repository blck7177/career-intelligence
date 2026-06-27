export interface CostSummaryRow {
  run_type: string;
  llm_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface RecentRun {
  id: string;
  run_type: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  llm_calls: number;
}

export interface UsageEvent {
  id: string;
  call_site: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  created_at: string | null;
}

export interface Workspace {
  id: string;
  name: string;
}

export interface RunError {
  task_id: string;
  task_type: string;
  task_status: string;
  task_error_code: string | null;
  task_error_message: string | null;
  attempt_count: number;
  invocation_id: string | null;
  agent_id: string | null;
  exit_code: number | null;
  agent_error_code: string | null;
  agent_error_message: string | null;
  agent_status: string | null;
}

export type TimeRange = "24h" | "7d" | "30d" | "all";
