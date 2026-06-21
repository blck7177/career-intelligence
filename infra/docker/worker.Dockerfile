FROM python:3.11-slim

# Install Node.js 24 and OpenClaw CLI (npm package).
# This container does NOT run "openclaw gateway" — it only uses "openclaw agent"
# to forward task invocations to the openclaw-gateway service.
ARG OPENCLAW_VERSION=2026.6.9

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg bash && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g openclaw@${OPENCLAW_VERSION} && \
    command -v openclaw && \
    rm -rf /var/lib/apt/lists/*

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
