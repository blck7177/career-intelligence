#!/usr/bin/env sh
# openclaw-entrypoint.sh
#
# Materializes a writable runtime copy of the OpenClaw config before starting
# the gateway. The repo source is mounted read-only at /app/agent-source;
# OpenClaw needs to write to its active OPENCLAW_CONFIG_PATH (atomic saves,
# last-known-good tracking), so we copy to the writable openclaw_config volume.
#
# Dev: re-copies on every container restart so config edits in the repo are
# picked up without rebuilding the image.
set -eu

CONFIG_SOURCE=/app/agent/openclaw/config/openclaw.json
CONFIG_RUNTIME=/openclaw/config/openclaw.json

mkdir -p /openclaw/config

if [ -f "$CONFIG_SOURCE" ]; then
    cp "$CONFIG_SOURCE" "$CONFIG_RUNTIME"
    echo "[openclaw-entrypoint] config materialized: $CONFIG_RUNTIME"
else
    echo "[openclaw-entrypoint] WARNING: source config not found at $CONFIG_SOURCE; gateway will use existing runtime config or defaults"
fi

exec dist/index.js gateway --allow-unconfigured
