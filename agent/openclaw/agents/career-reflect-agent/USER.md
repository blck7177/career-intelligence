# Workspace Context — career-reflect-agent

## Workspace Purpose

This workspace runs post-run strategy reflection. Each invocation analyzes a completed
discovery run and proposes strategy patches for future runs.

## Task Boundaries

- You analyze **one completed run per invocation**.
- You do **not** access external web sources — all needed data is in `input.json`.
- You write `reflection_report.md` (analysis) and `strategy_patch.json` (proposed patches).
- Strategy patches are **recommendations only** — the platform decides whether to apply them.

## Run Directory Layout

```
/app/data/agent_artifacts/<run_id>/<task_id>/
  input.json                ← read this first (contains run_summary, search_ledger, etc.)
  output_manifest.json      ← write this last (via career_write_manifest)
  reflection_report.md      ← your analysis and reasoning
  strategy_patch.json       ← proposed strategy changes (conforms to strategy_patch.schema.json)
```

## strategy_patch.json Schema

```json
{
  "run_id": "...",
  "patches": [
    {
      "field": "source_weights | search_keywords | excluded_sources",
      "action": "add | remove | adjust",
      "value": "...",
      "rationale": "..."
    }
  ]
}
```

See `tools/schemas/strategy_patch.schema.json` for full schema.

## Session Isolation

Each invocation gets an isolated session key. Do not share state with other runs.

## Stop Conditions

Stop and write the manifest when:
- Reflection report is complete and patches are proposed
- No meaningful patterns are identifiable (write minimal patches or empty list)
