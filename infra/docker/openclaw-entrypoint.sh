#!/usr/bin/env sh
# openclaw-entrypoint.sh
#
# Materializes writable runtime copies of config and agent workspaces from the
# read-only repo source before starting the gateway.
#
# Path layout:
#   /app/agent/openclaw/          repo source (read-only bind mount)
#     config/openclaw.json        source config
#     agents/<id>/                source agent workspace files (AGENTS.md, etc.)
#     skills/                     source skill definitions
#
#   /openclaw/config/openclaw.json   runtime config  (openclaw_config volume, writable)
#   /openclaw/workspace/agents/<id>/ runtime workspace (openclaw_workspace volume, writable)
#   /openclaw/state/                 runtime state    (openclaw_state volume, writable)
#
# Gateway auth token (required by OpenClaw 2026.6+ when bind=lan):
#   Priority: OPENCLAW_GATEWAY_TOKEN env > preserved token in existing runtime config > auto-generate
#
# Dev: re-copies config and workspaces on every container restart so repo edits
# are picked up without rebuilding the image.
set -eu

AGENT_SOURCE=/app/agent/openclaw
CONFIG_SOURCE="$AGENT_SOURCE/config/openclaw.json"
CONFIG_RUNTIME=/openclaw/config/openclaw.json

# --- gateway auth token ---
# Resolve token: env var wins; fall back to the token already in the runtime
# config (survives restarts inside the volume); last resort: generate a fresh one.
if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
    if [ -f "$CONFIG_RUNTIME" ]; then
        OPENCLAW_GATEWAY_TOKEN=$(python3 -c "
import json, sys
try:
    d = json.load(open('$CONFIG_RUNTIME'))
    print(d.get('gateway', {}).get('auth', {}).get('token', ''), end='')
except Exception:
    pass
" 2>/dev/null || true)
    fi
    if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
        OPENCLAW_GATEWAY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(24))")
        echo "[openclaw-entrypoint] Generated new gateway auth token (set OPENCLAW_GATEWAY_TOKEN in .env to persist across rebuilds)"
    else
        echo "[openclaw-entrypoint] Restored gateway auth token from existing runtime config"
    fi
fi
export OPENCLAW_GATEWAY_TOKEN

# --- config ---
mkdir -p /openclaw/config
if [ -f "$CONFIG_SOURCE" ]; then
    cp "$CONFIG_SOURCE" "$CONFIG_RUNTIME"
    # Inject the resolved auth token into the runtime config so the gateway
    # finds it as a file-level setting too (belt-and-suspenders for hot reload).
    python3 -c "
import json
d = json.load(open('$CONFIG_RUNTIME'))
gw = d.setdefault('gateway', {})
auth = gw.setdefault('auth', {})
auth['mode'] = 'token'
auth['token'] = '${OPENCLAW_GATEWAY_TOKEN}'
json.dump(d, open('$CONFIG_RUNTIME', 'w'), indent=2)
"
    echo "[openclaw-entrypoint] config materialized: $CONFIG_RUNTIME"
else
    echo "[openclaw-entrypoint] WARNING: source config not found at $CONFIG_SOURCE"
fi

# --- agent workspaces ---
mkdir -p /openclaw/workspace/agents

for AGENT_ID in career-search-agent career-reflect-agent career-research-agent; do
    SRC="$AGENT_SOURCE/agents/$AGENT_ID"
    DST="/openclaw/workspace/agents/$AGENT_ID"

    if [ -d "$SRC" ]; then
        rm -rf "$DST"
        cp -R "$SRC" "$DST"
        echo "[openclaw-entrypoint] workspace materialized: $DST"
    else
        echo "[openclaw-entrypoint] WARNING: source workspace not found at $SRC"
    fi
done

exec dist/index.js gateway --allow-unconfigured
