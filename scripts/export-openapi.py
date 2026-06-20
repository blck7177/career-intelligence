#!/usr/bin/env python3
"""
Export FastAPI OpenAPI spec to openapi.json.

Usage:
    python scripts/export-openapi.py
    python scripts/export-openapi.py --output apps/web/openapi.json

Run this whenever API routes or Pydantic models change.
The generated file is the source of truth for the TypeScript client.
"""

import argparse
import json
import sys
from pathlib import Path


def export_openapi(output_path: str) -> None:
    try:
        from apps.api.main import app
    except ImportError as exc:
        print(f"ERROR: Could not import FastAPI app: {exc}", file=sys.stderr)
        print("Make sure you're running from the repo root with deps installed.", file=sys.stderr)
        sys.exit(1)

    schema = app.openapi()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2))
    print(f"OpenAPI spec written to {output_path}")
    print(f"  Title:   {schema.get('info', {}).get('title')}")
    print(f"  Version: {schema.get('info', {}).get('version')}")
    print(f"  Paths:   {len(schema.get('paths', {}))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="apps/web/openapi.json")
    args = parser.parse_args()
    export_openapi(args.output)
