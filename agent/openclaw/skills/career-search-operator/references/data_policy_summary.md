# Data Policy — Discovery Run

## Allowed Sources (public, no login)

- Public company career pages (direct URL, no login)
- LinkedIn public search results (no login, no LinkedIn API)
- Indeed / Glassdoor public pages
- Google / Bing search results (discovery surface only — result pages are NOT candidate URLs)

## Prohibited

- Do NOT log into any platform, bypass paywalls, or simulate login
- Do NOT save PII (candidate personal info, internal employee info)
- Do NOT write to the database — candidates go through `career_log_candidates` only
- Do NOT call wrappers not on the exec allowlist

## Budget

From `payload.budget`:

| Field | Meaning | Default |
|-------|---------|---------|
| `max_tool_calls` | Hard limit on total tool calls | 30 |
| `max_candidates` | **Target** candidate count — keep searching until close to this number | 50 |
| `max_new_sources` | Max new sources to add | 10 |
| `timeout_seconds` | Wall clock timeout (platform enforced) | 900 |

`max_candidates` is your search **target**, not just a ceiling. Use `career_search_status` after every 5 tool calls to check progress toward this target.
