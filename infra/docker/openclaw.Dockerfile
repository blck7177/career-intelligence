FROM ghcr.io/openclaw/openclaw:2026.2.26

USER root

# Keep wrapper runtime compatible with existing exec-approvals.json.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates curl && \
    ln -sf /usr/bin/python3 /usr/local/bin/python3 && \
    python3 -m pip install --break-system-packages --no-cache-dir click httpx && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY tools/wrappers/agent_tools/ /app/tools/wrappers/agent_tools/
COPY agent/openclaw/ /app/agent/openclaw/

# OpenClaw state and workspace are mounted as volumes at runtime
RUN mkdir -p /openclaw/state /openclaw/workspace /app/data/agent_artifacts \
 && chown -R node:node /openclaw /app/data/agent_artifacts

ENV OPENCLAW_STATE_DIR=/openclaw/state
ENV OPENCLAW_CONFIG_PATH=/app/agent/openclaw/config/openclaw.json

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
    CMD curl -fsS http://127.0.0.1:18789/readyz || exit 1

CMD ["dist/index.js", "gateway", "--allow-unconfigured"]
