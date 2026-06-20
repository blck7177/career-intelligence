# Agent Instructions

> This file is for Cursor IDE agents navigating this repo.
> For OpenClaw agent workspace bootstrap files, see `agent/openclaw/agents/`.

## 1. Read Order

Before working on any task, read in this order:

1. `PROJECT_OBJECTIVE.md` — project goal, scope, constraints
2. `AGENTS.md` (this file) — project navigation and operating rules
3. `docs/architecture.md` — system architecture and module boundaries
4. Relevant `protocols/*.md` — data policy, IO contracts, review gates
5. Relevant `agent/openclaw/skills/*/SKILL.md` — agent workflow instructions

## 2. Project Boundaries

**Agent may change freely:**
- `apps/` — application code
- `packages/` — library code
- `tests/` — test files
- `scripts/` — utility scripts
- `docs/` — documentation
- `agent/openclaw/agents/` — OpenClaw workspace bootstrap files
- `agent/openclaw/skills/` — skill instructions (with review for behavior changes)
- `tools/wrappers/agent_tools/` — Python wrappers for OpenClaw

**Agent must not change without human review:**
- `protocols/` — stable project rules (changes require explicit review)
- `configs/` — human-owned configuration files
- `PROJECT_OBJECTIVE.md` — project scope and goals
- `agent/openclaw/config/exec-approvals.json` — security allowlist

**configs/ write rule:**
- `configs/company_boards.yaml` may only be written via `tools/wrappers/platform_tools/career_register_board`

## 3. Standard Workflow

1. Read `PROJECT_OBJECTIVE.md` and relevant protocols
2. Identify the relevant skill or module
3. Propose a minimal plan before modifying files
4. Implement changes
5. Run validation (`pytest`, schema checks, type checks)
6. Summarize changes and decisions made
7. Flag unresolved issues

## 4. Required Checks

Before marking any task complete:

```bash
# Python: from repo root
python -m pytest tests/ -x -q

# TypeScript: from apps/web/
npm run typecheck

# API contract: ensure openapi.json is up to date
python scripts/export-openapi.py
```

## 5. Module Boundary Rules

```
packages/domain/        — NO imports from FastAPI, SQLAlchemy, Redis, Celery, OpenAI
packages/contracts/     — Pydantic only, no IO
packages/infrastructure/agent_runtime/ — ONLY place that calls OpenClaw CLI
agent/openclaw/         — OpenClaw reads this; no Python imports here
tools/wrappers/agent_tools/ — ONLY entry point for OpenClaw exec (exec allowlist)
```

## 6. Stop Conditions

Stop and ask for human review when:
- Any change would modify `protocols/` semantics
- Any change would broaden `agent/openclaw/config/exec-approvals.json`
- Any change would give OpenClaw access to DB credentials or internal APIs
- Validator gate logic would be loosened
- A migration would drop or modify existing columns in a breaking way
- Any external write action (send email, post to external API, etc.)

## 7. Common Mistakes

- Do not let OpenClaw write directly to Postgres — it writes staged artifacts only
- Do not hand-write TypeScript types in `apps/web/` — use `src/api/generated/`
- Do not put project-specific logic in global OpenClaw skills
- Do not store business state in Redis — only queue messages, locks, and cache
- Do not reuse session keys across runs — each run/task/attempt gets a new key
- Do not expose `openclaw_session` or `skill_path` in API responses to the frontend
