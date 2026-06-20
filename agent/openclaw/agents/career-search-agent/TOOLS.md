# Tools Available to career-search-agent

## Built-in Tools

- `web_search(query)` — search the web
- `web_fetch(url)` — fetch a URL and return text content

## Approved Wrappers (via exec tool)

All wrappers accept `--task-spec <path> --output <path>`.

### career_search_status

Query current search session budget and coverage.

```
python /app/tools/wrappers/agent_tools/career_search_status.py \
  --task-spec /path/to/input.json \
  --output /path/to/status_output.json
```

Output: `{ "candidates_logged": N, "tool_calls_used": N, "budget_remaining": N }`

### career_log_candidates

Write one or more triaged candidates to the candidate pool.

```
python /app/tools/wrappers/agent_tools/career_log_candidates.py \
  --task-spec /path/to/input.json \
  --output /path/to/log_output.json
```

Payload (in task-spec `candidates` field): list of `{ url, title, company, source_type }`.

### career_write_manifest

Write the final output manifest. Call once when done.

```
python /app/tools/wrappers/agent_tools/career_write_manifest.py \
  --task-spec /path/to/manifest_data.json \
  --output /path/to/output_manifest.json
```

### career_fetch_source

Fetch and normalize a job posting from a specific ATS URL.

```
python /app/tools/wrappers/agent_tools/career_fetch_source.py \
  --task-spec /path/to/fetch_spec.json \
  --output /path/to/fetch_result.json
```

## What NOT to Use

- Do not use `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use `curl`, `wget`, or any HTTP tool outside the approved wrappers
