# Architecture

## Overview

Career OpenClaw is a contract-first modular monolith deployed as Dockerized services. The system separates deterministic platform work (API, validation, persistence) from non-deterministic agent work (discovery, research, reflection) via a strict boundary:

```
Celery     — deterministic scheduling
OpenClaw   — non-deterministic reasoning / search / execution
Validator  — artifact acceptance gate
Postgres   — source of truth (facts only)
Redis      — queue + lock + cache (no business state)
Frontend   — reads API contract only
```

## Service Map

```
Browser
  → nginx (sole public entry point)
    → apps/web (Next.js, generated TS SDK)
      → apps/api (FastAPI, auth / validation / enqueue)
        → Postgres (run/task state)
        → Redis (task queue)
          → apps/worker (Celery)
            → packages/infrastructure/agent_runtime (adapter)
              → openclaw-gateway container
                → agent/openclaw/skills/*
                → tools/wrappers/agent_tools/* (exec allowlist only)
                → staged artifacts (shared volume)
            → Validator Gate
              → Postgres (validated facts)
```

## Module Responsibilities

| Module | Allowed | Forbidden |
|--------|---------|-----------|
| `apps/web` | Display, forms, poll run status, call generated SDK | DB, Redis, wrappers, agent details |
| `apps/api` | Validate requests, create run/task, enqueue, read status | Execute long tasks, call OpenClaw |
| `apps/worker` | Claim tasks, call agent_runtime or deterministic handlers, validate, persist | Expose HTTP endpoints, return data to frontend |
| `packages/domain` | Pure business logic | Import FastAPI, SQLAlchemy, Redis, Celery, OpenAI |
| `packages/contracts` | Pydantic DTOs and schemas | IO of any kind |
| `packages/infrastructure/agent_runtime` | Invoke OpenClaw gateway client, capture artifacts | Business decisions, DB writes, running openclaw-gateway |
| `openclaw-gateway` | Run OpenClaw, hold state/workspace/skills | Direct DB access, internal API calls |
| `Postgres` | Source of truth: runs/tasks/events/artifacts/jobs | Act as queue broker |
| `Redis` | Queue, distributed lock, short-term cache, rate limit | Store final business state |

## Agent Execution Flow

```
1. POST /api/runs  →  API creates run + task in Postgres, enqueues task_id via Redis
2. Celery worker claims task, marks running
3. domain/agent_jobs/planner.py builds AgentInvocationSpec
4. Worker writes input.json to shared agent_artifacts volume
5. infrastructure/agent_runtime/openclaw.py calls create_runtime() and invokes the
   openclaw CLI as a gateway client ("openclaw agent --session-key ...")
6. The CLI routes the invocation through the openclaw-gateway daemon via the shared
   openclaw_state volume socket. The gateway owns agent workspace, exec sandbox,
   skills, and session state. The worker does not mount local agent/openclaw config.
7. Gateway executes the skill; agent reads input.json, writes output_manifest.json
8. Worker reads manifest, runs Validator Gate (5 validators)
9. Pass → write jobs/artifacts/events to Postgres, mark task succeeded
10. Fail → mark task needs_review, write agent_validation_results
11. UI polls GET /api/runs/{run_id} and renders result
```

**The `worker-agent` container is a gateway CLIENT, not a gateway host.**
See `docs/runbook.md §13` for runtime boundary details.

## Task Types

| task_type | Execution Mode | Handler |
|-----------|---------------|---------|
| `agent.job_discovery` | OPENCLAW | career-search-agent |
| `agent.job_research` | OPENCLAW | career-research-agent |
| `agent.run_reflection` | OPENCLAW | career-reflect-agent |
| `job_report` | DETERMINISTIC | LLM analysis pipeline |
| `fit_report` | DETERMINISTIC | Match analysis pipeline |

## Database Schema (core tables)

```
users / workspaces / workspace_members
runs           — run_type, status, input_snapshot_json
tasks          — run_id, task_type, status, attempt_count
task_events    — task_id, event_type, message, payload_json
artifacts      — run_id, artifact_type, storage_uri
jobs           — workspace_id, source, normalized_json

agent_invocations      — agent_id, session_key, input_spec_uri, output_manifest_uri, exit_code
agent_tool_events      — invocation_id, tool_name, action, status
agent_validation_results — invocation_id, validator_name, status, errors_json
```

## OpenClaw Boundary Rules

- OpenClaw reads: `input.json` from `agent_artifacts` volume
- OpenClaw writes: `output_manifest.json`, `candidate_jobs.jsonl`, `search_ledger.jsonl`, `trace_events.jsonl`
- OpenClaw CANNOT: write Postgres, call internal APIs, access `.env`, run arbitrary shell commands
- Exec allowlist: only `tools/wrappers/agent_tools/*.py` with `--task-spec / --output` interface

## Key Files

| Path | Purpose |
|------|---------|
| `packages/infrastructure/agent_runtime/base.py` | AgentRuntime interface |
| `packages/infrastructure/agent_runtime/openclaw.py` | OpenClawRuntime implementation |
| `packages/contracts/agents/invocation.py` | AgentInvocationSpec, AgentInvocationResult |
| `packages/contracts/agents/manifests.py` | AgentOutputManifest |
| `packages/contracts/agents/validation.py` | AgentValidationResult |
| `packages/domain/agent_jobs/routing.py` | ExecutionMode routing |
| `packages/domain/agent_jobs/planner.py` | AgentInvocationSpec builder |
| `agent/openclaw/config/exec-approvals.json` | Exec security allowlist |
| `agent/openclaw/config/openclaw.json` | OpenClaw runtime config |
| `apps/worker/router.py` | Task type → execution mode routing |
| `scripts/export-openapi.py` | Export FastAPI OpenAPI spec |
| `scripts/generate-web-client.sh` | Generate TypeScript SDK from spec |
