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
| `max_tool_calls` | Total tool call limit | 30 |
| `max_candidates` | Max candidates to log | 50 |
| `max_new_sources` | Max new sources to add | 10 |
| `timeout_seconds` | Wall clock timeout (platform enforced) | 900 |

Use `career_search_status` periodically to check usage.
