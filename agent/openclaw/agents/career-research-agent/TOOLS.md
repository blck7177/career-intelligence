# Tools Available to career-research-agent

## Built-in Tools

- `web_search(query)` — search the web for company and job information
- `web_fetch(url)` — fetch a URL and return text content

## Approved Wrappers (via exec tool)

All wrappers accept `--task-spec <path> --output <path>`.

### career_fetch_source

Fetch and normalize a job posting or company page from a URL.

```
python3 /app/tools/wrappers/agent_tools/career_fetch_source.py \
  --task-spec /path/to/fetch_spec.json \
  --output /path/to/fetch_result.json
```

task-spec fields: `{ "url": "...", "source_type": "...", "run_id": "...", "task_id": "..." }`

Output: normalized page text and metadata.

### career_write_manifest

Write the final output manifest. Call once when all research is complete.

```
python3 /app/tools/wrappers/agent_tools/career_write_manifest.py \
  --task-spec /path/to/manifest_data.json \
  --output /path/to/output_manifest.json
```

task-spec fields:
- `invocation_id`, `status` (`completed`|`partial`|`failed`), `stop_reason`
- `artifact_paths`: `{ "research_notes": "...", "sources": "..." }`
- `summary`: `{ "job_id": "...", "citations_count": N }`

## What NOT to Use

- Do not use `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use `curl`, `wget`, or any HTTP tool outside the approved wrappers
- Do not fabricate information — every claim in research_notes.md must have a cited URL
