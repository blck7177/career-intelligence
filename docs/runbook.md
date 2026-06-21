# Runbook

Operational reference for career-openclaw-v2.

For architecture context see [architecture.md](architecture.md).  
For project goals and constraints see [../PROJECT_OBJECTIVE.md](../PROJECT_OBJECTIVE.md).

---

## 1. Dev Setup

### Prerequisites

- Docker + Docker Compose v2
- Python 3.12, Node 20
- `cp .env.example .env` then fill in `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

### First-time setup

```bash
# Python environment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Node environment (web)
cd apps/web && npm install && cd ../..

# Run database migrations
DATABASE_URL=postgresql://career:career@localhost:5432/career_openclaw \
  alembic upgrade head
```

### Start the full dev stack

```bash
# Bring up all 8 services (postgres, redis, openclaw-gateway, api, worker-fast, worker-agent, web, nginx)
docker compose -f infra/compose/docker-compose.dev.yml up

# Or use the helper script (starts infra via Docker, processes via tmux or local terminals)
./scripts/dev_up.sh
```

Services once running:

| Service          | URL                          |
|------------------|------------------------------|
| Web UI           | http://localhost:3000        |
| FastAPI (API)    | http://localhost:8000        |
| API docs         | http://localhost:8000/docs   |
| Celery Flower    | http://localhost:5555        |
| nginx (entry)    | http://localhost:80          |

---

## 2. Run Database Migrations

```bash
# Apply all pending migrations
DATABASE_URL=postgresql://career:career@localhost:5432/career_openclaw \
  alembic upgrade head

# Check current revision
alembic current

# Generate a new migration after changing models.py
alembic revision --autogenerate -m "describe the change"
```

Migrations live in `packages/infrastructure/db/migrations/versions/`.

---

## 3. Run Workers Manually (without Docker)

Start infrastructure first (postgres + redis):

```bash
docker compose -f infra/compose/docker-compose.dev.yml up postgres redis -d
```

Then start workers in separate terminals:

```bash
# Fast worker — deterministic tasks (job_report, fit_report)
celery -A apps.worker.celery_app worker \
  --loglevel=info --queues=fast --concurrency=2

# Agent worker — OpenClaw tasks (job_discovery, job_research, run_reflection)
# Requires openclaw-gateway to be running
celery -A apps.worker.celery_app worker \
  --loglevel=info --queues=agent --concurrency=1
```

---

## 4. Trigger a Discovery Run

```bash
# POST to create a run (returns run_id immediately)
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "dev_default",
    "run_type": "job_discovery",
    "input_snapshot": {}
  }'

# Response: {"id": "run_abc", "status": "queued", ...}
```

Available `run_type` values and the task type they create:

| run_type         | task_type             | worker queue | executor   |
|------------------|-----------------------|--------------|------------|
| `job_discovery`  | `agent.job_discovery` | `agent`      | OpenClaw   |
| `job_research`   | `agent.job_research`  | `agent`      | OpenClaw   |
| `run_reflection` | `agent.run_reflection`| `agent`      | OpenClaw   |
| `job_report`     | `job_report`          | `fast`       | Deterministic |
| `fit_report`     | `fit_report`          | `fast`       | Deterministic |

---

## 5. Check Task Status and Events

```bash
RUN_ID="run_abc"

# Run status
curl http://localhost:8000/api/runs/$RUN_ID

# Task list (shows status per task)
curl http://localhost:8000/api/runs/$RUN_ID/tasks

# Event log (append-only, for progress display)
curl http://localhost:8000/api/runs/$RUN_ID/events

# Agent invocations (debug: OpenClaw execution details)
curl http://localhost:8000/api/runs/$RUN_ID/agent-invocations

# Cancel a run
curl -X POST http://localhost:8000/api/runs/$RUN_ID/cancel
```

Task status machine: `queued → running → succeeded | failed | cancelled | needs_review`

`needs_review` means the Validator Gate rejected the agent's output. Check
`/agent-invocations` for `agent_validation_results` to see which validator failed and why.

---

## 6. Re-running Failed Tasks

Tasks that land in `failed` or `needs_review` are not automatically retried beyond
`max_attempts` (default: 3). To re-trigger:

```bash
# Create a new run of the same type — the old run is immutable
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "dev_default", "run_type": "job_discovery", "input_snapshot": {}}'
```

Each run gets a new `correlation_id` for log tracing.

---

## 7. Regenerate the OpenAPI Client

The TypeScript client in `apps/web/src/api/generated/schema.d.ts` must always
reflect the current FastAPI schema. Run this after any API contract change:

```bash
# Export openapi.json from the running FastAPI app
python scripts/export-openapi.py

# Regenerate TypeScript types
./scripts/generate-web-client.sh

# Check the generated file is in sync (used in CI)
./scripts/check-openapi-contract.sh
```

Never edit `apps/web/src/api/generated/schema.d.ts` by hand. CI will fail if the
committed version diverges from the generated one.

---

## 8. Run Tests

```bash
# Unit + contract tests (no Docker required)
python -m pytest tests/ -x -q --ignore=tests/integration

# Worker routing and validator gate only
python -m pytest tests/worker/ -v

# Agent contract and smoke tests (no live DB or OpenClaw)
python -m pytest tests/contract/ tests/integration/ -v

# Full integration tests (requires running Docker stack)
python -m pytest tests/ -m integration -v
```

---

## 9. Key Environment Variables

| Variable               | Default                                          | Notes                                    |
|------------------------|--------------------------------------------------|------------------------------------------|
| `DATABASE_URL`         | `postgresql://career:career@localhost:5432/...`  | Postgres connection string               |
| `REDIS_URL`            | `redis://localhost:6379/0`                       | Broker and cache                         |
| `OPENAI_API_KEY`       | —                                                | Required for LLM calls                   |
| `ANTHROPIC_API_KEY`    | —                                                | Alternative LLM provider                 |
| `LLM_MODEL`            | `claude-opus-4-5`                                | Model identifier                         |
| `OPENCLAW_BIN`         | `openclaw`                                       | Path to OpenClaw CLI                     |
| `OPENCLAW_CONFIG_PATH` | `/app/agent/openclaw/config/openclaw.json`       | Gateway runtime config (worker 可不设置) |
| `OPENCLAW_STATE_DIR`   | `/openclaw/state`                                | OpenClaw session state volume            |
| `AGENT_ARTIFACTS_DIR`  | `/app/data/agent_artifacts`                      | Shared volume for staged agent output    |
| `LOG_LEVEL`            | `INFO`                                           | `DEBUG` / `INFO` / `WARNING` / `ERROR`   |
| `LOG_JSON`             | `1`                                              | Set `0` for human-readable dev output    |
| `ENV`                  | `development`                                    | `production` disables `/docs`            |
| `DEV_MODE`             | `0`                                              | `1` enables auto-create dev workspace    |
| `CORS_ORIGINS`         | `http://localhost:3000`                          | Comma-separated allowed origins          |

---

## 10. OpenClaw Workspace

Agent workspace files live in `agent/openclaw/`. These are **read by OpenClaw**, not by Python:

```
agent/openclaw/
  config/
    openclaw.json        — agent/tool/session config
    exec-approvals.json  — allowlist (only wrappers/agent_tools/ permitted)
  agents/
    career-search-agent/ — AGENTS.md, TOOLS.md, USER.md
    career-research-agent/
    career-reflect-agent/
  skills/
    career-search-operator/SKILL.md
    career-research-operator/SKILL.md
    career-reflect-operator/SKILL.md
```

**Never** modify `agent/openclaw/config/exec-approvals.json` without human review.
Broadening the allowlist is a Stop Condition (see `AGENTS.md`).

---

## 11. Logs and Observability

All services emit structured JSON logs (NDJSON) to stdout. Each log line includes:

- `timestamp` — ISO-8601 UTC
- `level`, `logger`, `message`
- `correlation_id` — ties API request → Celery task → DB writes

```bash
# Stream logs from all services
docker compose -f infra/compose/docker-compose.dev.yml logs -f

# Filter by correlation_id (requires jq)
docker compose -f infra/compose/docker-compose.dev.yml logs -f \
  | jq 'select(.correlation_id == "YOUR_CORRELATION_ID")'

# Celery task dashboard
open http://localhost:5555
```

---

## 12. Production Deployment Checklist

Before going to production:

- [ ] Set all required env vars (no empty API keys)
- [ ] Run `alembic upgrade head` against production Postgres
- [ ] Verify `openclaw-gateway` healthcheck passes: `docker compose exec openclaw-gateway openclaw --version`
- [ ] Run `./scripts/check-openapi-contract.sh` — no stale spec
- [ ] Set `ENV=production` (disables `/docs` and `/redoc`)
- [ ] Set `LOG_JSON=1` (ensure structured logs)
- [ ] Confirm `exec-approvals.json` is in allowlist mode
- [ ] Confirm no DB credentials are reachable from within the openclaw-gateway container
- [ ] Confirm `worker-agent` image has openclaw CLI installed (`openclaw --version`)
- [ ] Confirm `worker-agent` mounts `openclaw_state` (gateway socket) and `agent_artifacts` only
- [ ] Verify `OPENCLAW_STATE_DIR=/openclaw/state` is set on `worker-agent`

---

## 13. Gateway Client Architecture

**The `worker-agent` container is a gateway client — it does NOT run OpenClaw locally.**

```
worker-agent  →  "openclaw agent ..." CLI  →  openclaw-gateway container
                 (thin client shim)               (sole execution host)
```

The `openclaw-gateway` container owns:
- All OpenClaw runtime state (`/openclaw/state`)
- Agent workspace, skills, session files
- `exec-approvals.json` enforcement
- Wrapper script execution sandbox

The `worker-agent` container needs:
- `openclaw` CLI binary (for `openclaw agent` client calls)
- Shared `openclaw_state` volume (for gateway socket discovery)
- Shared `agent_artifacts` volume (for input.json / output_manifest.json exchange)

**Never configure `worker-agent` to run `openclaw gateway`.**

---

## 14. Validator Gate Rules (v2)

The `ValidatorGate` runs five validators on every agent manifest before any DB write:

| Validator | What it checks |
|-----------|----------------|
| `schema` | `invocation_id` matches spec; `status != failed`; `stop_reason` present |
| `provenance` | All declared artifact files exist; discovery requires `coverage_report` artifact |
| `budget` | `candidate_count` within expected range relative to `max_tool_calls` |
| `tool_activity` | Discovery three-state gate (see below); research tool-evidence check |
| `discovery_count` | `manifest.candidate_count` matches actual `candidate_pool.jsonl` line count |

### Discovery three-state gate

| State | Condition | Result |
|-------|-----------|--------|
| A — no discovery | No `trace_events` or no discovery tool in trace | **FAIL** → `needs_review` |
| B — valid no-yield | `trace_events` with discovery tool, `candidate_count == 0` | **PASS** |
| C — candidates found | `trace_events` with discovery tool, `candidate_count > 0` | **PASS** |

Placeholder runs (agent writes manifest without executing real `web_search`/`web_fetch`/wrappers) are always caught by State A and land in `needs_review`.

### Research tool-evidence check

If `citations_count > 0`, `trace_events` must contain evidence of `web_fetch` or `career_fetch_source`. Research reports fabricated without real fetches are rejected.

### `needs_review` meaning

A `needs_review` task means the Validator Gate rejected the agent output. Check:
```bash
curl http://localhost:8000/api/runs/{run_id}/agent-invocations
```
Look at `agent_validation_results` for the failing `validator_name` and `errors` array.
