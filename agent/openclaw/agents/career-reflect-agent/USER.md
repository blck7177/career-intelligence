# Workspace Context — career-reflect-agent

## Workspace Purpose

This workspace runs post-run strategy reflection. Each invocation analyzes a completed
discovery run and proposes strategy patches for future runs.

## Task Boundaries

- You analyze **one completed run per invocation**.
- You do **not** access external web sources — all needed data is in `input.json` and artifact paths it provides.
- You write `reflection_report.md` (analysis) and `strategy_patch.json` (proposed patches).
- Strategy patches are **recommendations only** — the platform worker validates and applies them.

## Run Directory Layout

```
/app/data/agent_artifacts/<run_id>/<task_id>/
  input.json                ← read this first (enriched payload from worker)
  output_manifest.json      ← write this last (via career_write_manifest)
  reflection_report.md      ← your analysis and reasoning
  strategy_patch.json       ← proposed strategy changes (conforms to strategy_patch.schema.json)
```

## input.json payload (worker-enriched)

The worker fills `payload` with:

- `reflected_run_id` — discovery run being analyzed
- `coverage_report_path`, `search_ledger_path`, `candidate_pool_path` — paths to read via read tool
- `reflected_run_summary` — stats from the completed discovery run (candidate_count, etc.)
- `current_strategy_state` — current cross-run strategy (may be null on first run)
- `max_tool_calls`, `timeout_seconds` — budget

Read artifact files from the paths provided; do not guess paths under legacy `runs/<session_id>/`.

## strategy_patch.json Schema

Flat object with **only** these optional fields (unknown fields are rejected):

```json
{
  "effective_sources": ["..."],
  "avoid_sources": ["domain — failure_reason"],
  "effective_query_patterns": ["..."],
  "avoid_query_patterns": ["..."],
  "coverage_by_role_category": { "market_risk_exposure": "weak" },
  "key_learnings": ["..."],
  "recommended_next_searches": ["..."]
}
```

See `tools/schemas/strategy_patch.schema.json` and `skills/career-reflect-operator/references/strategy_patch_contract.md` for merge semantics and taxonomy key rules.

## Session Isolation

Each invocation gets an isolated session key. Do not share state with other runs.

## Stop Conditions

Stop and write the manifest when:
- Reflection report is complete and patches are proposed
- No meaningful patterns are identifiable (write `{}` or minimal patch)
