FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[anthropic,openai]"

COPY apps/ apps/
COPY packages/ packages/
COPY configs/ configs/
COPY scripts/ scripts/
COPY alembic.ini .

RUN chmod +x scripts/start_api.sh

EXPOSE 8000

CMD ["bash", "scripts/start_api.sh"]
