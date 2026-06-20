#!/usr/bin/env bash
# Generate TypeScript SDK from OpenAPI spec.
#
# Requires: openapi-typescript (npm install -g openapi-typescript)
# Or: npx openapi-typescript
#
# Usage:
#   ./scripts/generate-web-client.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENAPI_JSON="$REPO_ROOT/apps/web/openapi.json"
OUT_DIR="$REPO_ROOT/apps/web/src/api/generated"

echo "=== Exporting OpenAPI spec ==="
python "$REPO_ROOT/scripts/export-openapi.py" --output "$OPENAPI_JSON"

echo "=== Generating TypeScript client ==="
cd "$REPO_ROOT/apps/web"
npx openapi-typescript "$OPENAPI_JSON" --output "$OUT_DIR/schema.d.ts"

echo "=== TypeScript client written to $OUT_DIR ==="
echo "Import types with: import type { components } from '@/api/generated/schema'"
