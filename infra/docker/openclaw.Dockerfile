FROM python:3.11-slim

# Install OpenClaw
RUN pip install --no-cache-dir openclaw-sdk || \
    (curl -fsSL https://install.openclaw.ai | sh)

WORKDIR /app

# Install Python deps for wrappers
RUN pip install --no-cache-dir click httpx

COPY tools/wrappers/agent_tools/ /app/tools/wrappers/agent_tools/
COPY agent/openclaw/ /app/agent/openclaw/

# OpenClaw state and workspace are mounted as volumes at runtime
RUN mkdir -p /openclaw/state /openclaw/workspace /app/data/agent_artifacts

ENV OPENCLAW_CONFIG_PATH=/app/agent/openclaw/config/openclaw.json
ENV OPENCLAW_STATE_DIR=/openclaw/state

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD openclaw --version || exit 1

CMD ["openclaw", "gateway", "--config", "/app/agent/openclaw/config/openclaw.json"]
