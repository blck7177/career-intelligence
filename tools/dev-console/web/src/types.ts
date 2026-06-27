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
