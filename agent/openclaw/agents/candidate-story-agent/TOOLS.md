# Tools Available to candidate-story-agent

## Built-in Tools

- `web_search(query)` — search to answer one specific question raised during
  the interview. Do NOT use to search for the candidate by name, or for
  generic role/background context.
- `web_fetch(url)` — read specific pages to answer that question.

## Approved Wrappers (via exec tool)

### career_write_manifest

Write the final output manifest. Call once, after the investigation
transcript is written.

```
python3 /app/tools/wrappers/agent_tools/career_write_manifest.py \
  --task-spec /path/to/manifest_data.json \
  --output ./manifest_write_result.json
```

task-spec fields:
- `invocation_id`, `status` (`completed`|`partial`|`failed`), `stop_reason`
- `profile_id`, `experiences_investigated`
- `artifact_paths`: `{ "investigation_transcript": "..." }`
- `summary`: `{ "profile_id": "...", "experiences_investigated": N }`

## What NOT to Use

- Do not use `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use `curl`, `wget`, or any HTTP tool outside the approved wrappers
- Do not search for the candidate by name or for company-internal processes
