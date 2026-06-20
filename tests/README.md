# Tests

Test suite for Career OpenClaw.

## Structure

```
tests/
  api/          — FastAPI endpoint tests (uses TestClient)
  contract/     — Contract tests: Pydantic model validation, schema checks
  integration/  — Integration tests: DB, Redis, worker (require running services)
  worker/       — Celery task handler unit tests (mocked IO)
```

## Running Tests

```bash
# From repo root — all tests (unit + contract, excludes integration)
python -m pytest tests/ -x -q --ignore=tests/integration

# Integration tests (require docker compose up)
python -m pytest tests/integration/ -x -q

# With coverage
python -m pytest tests/ -x -q --ignore=tests/integration --cov=packages --cov=apps
```

## Test Rules

- Unit tests must not import FastAPI, SQLAlchemy, Redis, Celery — mock all IO
- Contract tests validate Pydantic models and JSON schema compliance only
- Integration tests may use real DB/Redis but must clean up after themselves
- All tests must be deterministic and runnable offline (except integration)
