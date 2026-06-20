#!/usr/bin/env bash
# check-openapi-contract.sh
#
# CI contract check: regenerate openapi.json and fail if the committed version
# is out of date with the current API code.
#
# Usage:
#   ./scripts/check-openapi-contract.sh [--fix]
#
# --fix: overwrite committed openapi.json with the freshly generated one.
#
# Exit codes:
#   0 — openapi.json is up to date (or --fix was used and it was refreshed)
#   1 — openapi.json is stale (diff detected); commit the regenerated version
#
# How to run in CI:
#   - Start the FastAPI app (or set EXPORT_ONLY=1 to use importlib)
#   - Run this script
#   - Fail the PR if it exits 1
#
# Dependencies: python, git, diff (standard POSIX tools)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMMITTED_SPEC="$REPO_ROOT/apps/web/openapi.json"
GENERATED_SPEC="$REPO_ROOT/.ci-openapi-generated.json"
FIX_MODE=0

for arg in "$@"; do
  [[ "$arg" == "--fix" ]] && FIX_MODE=1
done

echo "[contract-check] Regenerating openapi.json from current FastAPI app…"
cd "$REPO_ROOT"

# Export openapi.json without starting a server (static export)
python scripts/export-openapi.py --output "$GENERATED_SPEC"

echo "[contract-check] Diffing against committed spec…"

if diff -u "$COMMITTED_SPEC" "$GENERATED_SPEC" > /dev/null 2>&1; then
  echo "[contract-check] ✓  openapi.json is up to date."
  rm -f "$GENERATED_SPEC"
  exit 0
fi

echo "[contract-check] DIFF DETECTED:"
diff -u "$COMMITTED_SPEC" "$GENERATED_SPEC" || true

if [[ "$FIX_MODE" -eq 1 ]]; then
  cp "$GENERATED_SPEC" "$COMMITTED_SPEC"
  rm -f "$GENERATED_SPEC"
  echo "[contract-check] openapi.json updated. Commit the change."
  exit 0
fi

rm -f "$GENERATED_SPEC"
echo ""
echo "[contract-check] ✗  openapi.json is STALE."
echo "   Run: ./scripts/check-openapi-contract.sh --fix"
echo "   Then regenerate the TypeScript client: ./scripts/generate-web-client.sh"
echo "   Then commit both files."
exit 1
