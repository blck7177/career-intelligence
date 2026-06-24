# Tools Available to career-search-agent

## Built-in Tools

- `web_search(query)` — search the web
- `web_fetch(url)` — fetch a URL and return text content
- `file_write(path, content)` — write a file; use `./` paths to write in your workspace

## Approved Wrappers (via exec tool)

**CRITICAL — These wrappers MUST be called via exec.**
Do NOT use `file_write` to write candidate data or manifests directly.
Only calls through these exec wrappers create the signed `tool_events.jsonl` ledger required for validation.

**PATH RULES — read carefully:**

- All `--task-spec` files must be written by you first using `file_write ./spec.json …`
  so the subprocess can find them.
- All `--output` files must use `./` prefix (workspace-relative).  The subprocess CWD
  is your workspace, so `./result.json` lands in your workspace and you can read it
  back with `print lines 1-N from ./result.json`.
- Exception: `career_write_manifest --output` must use the exact `output_manifest_path`
  from your task spec (an absolute path on the artifact volume).

---

### career_search_status

Query current session budget and coverage.

**Step 1 — write spec:**
```json
{
  "run_id": "<run_id from your task spec>",
  "task_id": "<task_id from your task spec>",
  "budget": { "max_tool_calls": 15, "max_candidates": 20 }
}
```
→ `file_write ./status_spec.json <above JSON>`

**Step 2 — run:**
```
/usr/local/bin/python3 /app/tools/wrappers/agent_tools/career_search_status.py \
  --task-spec ./status_spec.json \
  --output ./status.json
```

**Step 3 — read:**
```
print lines 1-30 from ./status.json
```

Output: `{ "candidates_logged": N, "tool_calls_used": N, "budget_remaining": { "candidates": N, "tool_calls": N } }`

---

### career_log_candidates

Log one or more confirmed job candidates to the candidate pool.

**Step 1 — write spec (include all candidates you want to log):**
```json
{
  "run_id": "<run_id>",
  "task_id": "<task_id>",
  "invocation_id": "<invocation_id from task spec>",
  "artifacts_dir": "/app/data/agent_artifacts",
  "output_paths": {
    "tool_events_path": "<payload.output_paths.tool_events_path from task spec>"
  },
  "candidates": [
    {
      "url": "https://boards.greenhouse.io/company/jobs/12345",
      "title": "Market Risk Analyst",
      "company": "Example Bank",
      "source_type": "greenhouse"
    }
  ]
}
```
→ `file_write ./log_spec.json <above JSON>`

**Step 2 — run:**
```
/usr/local/bin/python3 /app/tools/wrappers/agent_tools/career_log_candidates.py \
  --task-spec ./log_spec.json \
  --output ./log_result.json
```

**Step 3 — read:**
```
print lines 1-20 from ./log_result.json
```

Output: `{ "logged": N, "errors": [] }`

---

### career_fetch_source

Fetch and normalize a job posting from a specific ATS URL.

**Step 1 — write spec:**
```json
{
  "url": "https://boards.greenhouse.io/company/jobs/12345",
  "source_type": "greenhouse",
  "run_id": "<run_id>",
  "task_id": "<task_id>"
}
```
→ `file_write ./fetch_spec.json <above JSON>`

**Step 2 — run:**
```
/usr/local/bin/python3 /app/tools/wrappers/agent_tools/career_fetch_source.py \
  --task-spec ./fetch_spec.json \
  --output ./fetch_result.json
```

**Step 3 — read:**
```
print lines 1-40 from ./fetch_result.json
```

---

### career_write_manifest

Write the final output manifest.  Call **once** at the very end before stopping.

**Step 1 — write spec:**
```json
{
  "invocation_id": "<invocation_id from task spec>",
  "run_id": "<run_id from task spec>",
  "task_id": "<task_id from task spec>",
  "status": "completed",
  "stop_reason": "max_candidates_reached",
  "candidate_count": 2,
  "sources_tried": ["greenhouse.io"],
  "sources_added": [],
  "output_paths": {
    "tool_events_path": "<payload.output_paths.tool_events_path from task spec>"
  },
  "artifact_paths": {
    "candidate_pool": "<output_paths.candidate_pool_path from task spec>",
    "search_ledger": "<output_paths.search_ledger_path from task spec>",
    "trace_events": "<output_paths.trace_events_path from task spec>",
    "coverage_report": "<output_paths.coverage_report_path from task spec>"
  }
}
```
→ `file_write ./manifest_spec.json <above JSON>`

**Step 2 — run (use the exact output_manifest_path from your task spec):**
```
/usr/local/bin/python3 /app/tools/wrappers/agent_tools/career_write_manifest.py \
  --task-spec ./manifest_spec.json \
  --output <output_paths.output_manifest_path from task spec>
```

---

## What NOT to Use

- Do not use `bash`, `sh`, or any shell command directly
- Do not attempt database connections
- Do not use `curl`, `wget`, or any HTTP tool outside the approved wrappers
- Do not use paths like `/tmp/...` — they are outside your workspace sandbox and unreadable
