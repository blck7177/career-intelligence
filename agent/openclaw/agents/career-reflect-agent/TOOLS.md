# Tools Available to career-reflect-agent

## Built-in Tools

No web tools needed — reflection works on data provided in your task spec.

## Approved Wrappers (via exec tool)

All wrappers accept `--task-spec <path> --output <path>`.

### career_write_manifest

Write the final output manifest. Call once when reflection is complete.

```
python3 /app/tools/wrappers/agent_tools/career_write_manifest.py \
  --task-spec /path/to/manifest_data.json \
  --output ./manifest_write_result.json
```

Include `output_paths.output_manifest_path` in the task spec. The wrapper writes the
platform manifest to the canonical path — do not construct manifest paths manually.

task-spec fields:
- `invocation_id`, `status` (`completed`|`failed`), `stop_reason`
- `artifact_paths`: `{ "reflection_report": "...", "strategy_patch": "..." }`
- `summary`: `{ "run_id": "...", "patches_proposed": N }`

## What NOT to Use

- Do not use `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use web tools — you work only from the data in your task spec
- Do not directly apply strategy patches — write them to the manifest output only
- Do not make claims about specific candidates or individuals
