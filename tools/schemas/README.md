# Tool Schemas

JSON Schema definitions for CLI tool and agent tool I/O contracts.

---

## Purpose and Scope

These schemas serve the **CLI and agent tool layer** — they define the input and output
shapes for `tools/cli/` commands and `tools/wrappers/agent_tools/` wrappers.

They are **not** the source of truth for API contracts or worker/database state.

---

## Two Schema Layers — Do Not Confuse Them

| Layer | Location | Source of Truth For | Validated By |
|-------|----------|---------------------|--------------|
| **API / Worker / DB contracts** | `packages/contracts/` | FastAPI endpoints, Celery task envelopes, DB repository inputs, Validator Gate | Pydantic v2 |
| **CLI / agent tool I/O contracts** | `tools/schemas/` (this folder) | CLI input validation, agent wrapper output shapes, skill reference contracts | `jsonschema` in wrappers |

Agents and developers: read `packages/contracts/` for anything involving the API,
database, or task queue. Read this folder for anything involving CLI commands or
agent tool wrappers.

---

## Schema Files

| File | Used By |
|------|---------|
| `job_record.schema.json` | Agent tool wrappers; normalized job record output contract |
| `candidate_pool_entry.schema.json` | `career_log_candidates.py` wrapper output |
| `candidate_profile.schema.json` | CLI query tools; search input |
| `discovery_intent.schema.json` | `payload.discovery_intent` in career-search-agent input.json (aligned with `packages/contracts/agents/discovery_intent.py`) |
| `search_agent_input.schema.json` | `career_search_status.py` wrapper |
| `search_objective.schema.json` | Legacy reference (career-openclaw Objective Controller; not used by career-intelligence runtime) |
| `search_query.schema.json` | Per-source search query |
| `research_bundle.schema.json` | `career-research-agent` output |
| `run_config.schema.json` | Run configuration input |
| `run_summary.schema.json` | `career-summarize-run` CLI output |
| `task.schema.json` | Task envelope reference (see also `packages/contracts/tasks/`) |
| `strategy_patch.schema.json` | `career-reflect-agent` strategy patch output |
| `fit_report.schema.json` | `career-validate-run` CLI output |
| `job_report.schema.json` | Job Intelligence Report output |

---

## Rule

> `packages/contracts/` is the **single source of truth** for business validation.
> Nothing in `tools/schemas/` affects what the Validator Gate accepts or rejects.
> Validator Gate only uses Pydantic models from `packages/contracts/agents/`.

If a schema here conflicts with a Pydantic model in `packages/contracts/`, the
Pydantic model wins. Update this schema to match, not the other way around.
