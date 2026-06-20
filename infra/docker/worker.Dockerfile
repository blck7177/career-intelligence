FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[anthropic,openai]"

COPY apps/ apps/
COPY packages/ packages/
COPY tools/ tools/
COPY alembic.ini .

# Default: fast worker (deterministic tasks).
# Override in docker-compose with the appropriate --queues and --concurrency:
#   worker-fast:  --queues=fast  --concurrency=2
#   worker-agent: --queues=agent --concurrency=1
CMD ["celery", "-A", "apps.worker.celery_app", "worker", "--loglevel=info", "--queues=fast", "--concurrency=2"]
