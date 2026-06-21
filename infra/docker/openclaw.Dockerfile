FROM ghcr.io/openclaw/openclaw:2026.6.9

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
COPY infra/docker/openclaw-entrypoint.sh /usr/local/bin/openclaw-entrypoint.sh

# openclaw/config is the writable runtime config volume (see openclaw-entrypoint.sh).
# openclaw/state and openclaw/workspace are mounted as volumes at runtime.
RUN chmod +x /usr/local/bin/openclaw-entrypoint.sh \
 && mkdir -p /openclaw/state /openclaw/config /openclaw/workspace /app/data/agent_artifacts \
 && chown -R node:node /openclaw /app/data/agent_artifacts

ENV OPENCLAW_STATE_DIR=/openclaw/state
# Points to the writable runtime copy materialized by openclaw-entrypoint.sh.
# The repo source at /app/agent/openclaw/config/openclaw.json is read-only.
ENV OPENCLAW_CONFIG_PATH=/openclaw/config/openclaw.json

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
    CMD curl -fsS http://127.0.0.1:18789/readyz || exit 1

USER node
CMD ["/usr/local/bin/openclaw-entrypoint.sh"]
