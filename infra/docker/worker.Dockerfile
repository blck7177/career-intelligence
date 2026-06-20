FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[anthropic,openai]"

COPY apps/ apps/
COPY packages/ packages/
COPY tools/ tools/

CMD ["celery", "-A", "apps.worker.celery_app", "worker", "--loglevel=info"]
