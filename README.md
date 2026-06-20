# Career OpenClaw v2

Agent-driven job intelligence platform. Discovers, researches, and structures job postings into a queryable database, with a web UI for browsing and analysis.

## Architecture

```
Browser → nginx → Next.js → FastAPI → Postgres / Redis → Celery Worker
                                                              ↓
                                                    OpenClaw Gateway
                                                    (bounded agents)
                                                              ↓
                                                    agent_artifacts volume
                                                              ↓
                                                    Validator Gate → Postgres
```

See `docs/architecture.md` for full module boundaries and data flow.

## Quick Start

```bash
# 1. Copy env
cp .env.example .env
# Fill in ANTHROPIC_API_KEY or OPENAI_API_KEY

# 2. Install Python deps
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,anthropic]"

# 3. Install web deps
cd apps/web && npm install && cd ../..

# 4. Start infrastructure + dev servers
./scripts/dev_up.sh

# 5. Run database migrations
./scripts/migrate.sh

# 6. Open the app
open http://localhost:3000
```

## Project Structure

```
apps/           Application entrypoints (web, api, worker)
packages/       Shared libraries (domain, contracts, infrastructure)
agent/          OpenClaw workspace configuration, agents, skills
tools/          Wrappers and CLI tools (deterministic, testable)
protocols/      Stable project rules and policies
configs/        Human-owned configuration files
docs/           Architecture, runbook, decisions
infra/          Docker, nginx, compose
scripts/        Dev utilities
tests/          All tests
```

## Key Rules

- `packages/domain/` has zero IO imports
- OpenClaw never writes to Postgres directly
- `tools/wrappers/agent_tools/` is the only exec allowlist entry point
- Frontend types are generated from OpenAPI — never hand-written
- Each agent invocation gets a unique, platform-generated session key

## Agent Navigation

See `AGENTS.md` for Cursor IDE agent navigation.
See `agent/openclaw/agents/*/AGENTS.md` for OpenClaw agent workspace constitutions.
