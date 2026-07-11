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

## Environments

This project supports two deployment modes via separate Docker Compose files.

### Development (current EC2 or local machine)

```bash
# 1. Copy and fill in env
cp .env.example .env

# 2. Start all services (Postgres + Redis run as containers)
docker compose -f infra/compose/docker-compose.dev.yml up -d

# 3. Run migrations
alembic upgrade head

# 4. Open http://localhost (nginx) or http://localhost:3000 (direct)
```

| Component        | How it runs                             |
|------------------|-----------------------------------------|
| Postgres         | Docker container, `postgres_data` volume |
| Redis            | Docker container, `redis_data` volume    |
| Reverse proxy    | Nginx, HTTP only (port 80)              |
| API              | Port 8000 exposed to host               |
| Web              | Port 3000 exposed to host               |
| Flower           | Port 5555 (Celery monitoring)           |
| Auth bypass      | `DEV_AUTH_BYPASS=true` allowed           |
| OpenAPI docs     | Enabled (`DEV_MODE=1`)                  |
| Backup sidecar   | Writes to `./backups/` on host          |

Config file: `.env` (copy from `.env.example`)
Compose file: `infra/compose/docker-compose.dev.yml`

### Production (dedicated EC2 + RDS)

```bash
# 1. Copy and fill in env (NEVER commit this file)
cp .env.prod.example .env.prod
chmod 600 .env.prod

# 2. Build and start (--env-file for compose-level variable interpolation)
docker compose --env-file .env.prod -f infra/compose/docker-compose.prod.yml up -d --build

# 3. Run migrations against RDS
DATABASE_URL=<rds-url> alembic upgrade head
```

| Component        | How it runs                              |
|------------------|------------------------------------------|
| Postgres         | AWS RDS (external, private VPC)          |
| Redis            | Docker container (internal only)         |
| Reverse proxy    | Caddy, auto HTTPS (ports 80 + 443)      |
| API              | No host port, behind Caddy              |
| Web              | No host port, behind Caddy              |
| Flower           | Removed                                 |
| Auth bypass      | Forbidden (`APP_ENV=production` enforced)|
| OpenAPI docs     | Disabled (`DEV_MODE=0`)                 |
| Backup sidecar   | pg_dump to `backup_data` volume          |

Config file: `.env.prod` (copy from `.env.prod.example`)
Compose file: `infra/compose/docker-compose.prod.yml`

### Key differences an agent must handle when setting up a new instance

1. **Database**: Dev uses Docker Postgres; prod uses RDS. Set `DATABASE_URL` in `.env.prod` to the RDS endpoint. Do NOT include a postgres service in prod compose.
2. **HTTPS**: Prod requires a domain name in `DOMAIN=` env var. Caddy auto-provisions TLS certificates via Let's Encrypt. Ensure ports 80 and 443 are open in the EC2 security group.
3. **Secrets**: Prod `.env.prod` must have strong passwords (`RDS_PASSWORD`, `OPENCLAW_GATEWAY_TOKEN`, `TOOL_LEDGER_SIGNING_KEY`). Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
4. **CORS**: Set `CORS_ORIGINS=https://yourdomain.com` to match the production domain exactly.
5. **Clerk auth**: Prod uses live keys (`pk_live_*`, `sk_live_*`). Update `CLERK_JWKS_URL` to point to the production Clerk instance.
6. **Security groups**: RDS must be in the same VPC as EC2, not publicly accessible. RDS SG allows inbound 5432 only from the EC2 SG. EC2 SG allows inbound 80, 443 (public) and 22 (your IP only).
7. **Backup**: The backup sidecar runs `pg_dump` every 6 hours with 7-day retention. In prod it connects to RDS via `RDS_HOST`/`RDS_USER`/`RDS_PASSWORD`/`RDS_DATABASE` env vars.
8. **DNS**: Point your domain to the EC2 Elastic IP via Route 53 or your DNS provider. Caddy needs the DNS to resolve before it can issue certificates.

### AWS resources needed for production

```
EC2          Ubuntu + Docker, security group: 80, 443, 22
Elastic IP   Bound to EC2 (stable IP across restarts)
RDS          Postgres 16, same VPC, private, automated backup on
S3 bucket    Private, for backup sync (phase 2)
IAM role     EC2 → S3 read/write (phase 2)
Route 53     Domain → Elastic IP
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
