# Candidate Evidence Contract

This is the **hardest rule set** in this skill. The platform uses HMAC-signed tool ledger (`tool_events.jsonl`) for anti-fabrication verification. Violations cause the entire run to enter `needs_review`.

## Entry Requirements (ALL must be met before calling career_log_candidates)

1. **URL is a real job posting** — not a search result page, not a company homepage, not a career listing page.
2. **Evidence exists** — `web_fetch` or `career_fetch_source` confirmed real JD content at this URL.
3. **Required fields**: `url` (valid http/https), `title`, `company`, `source_type`
4. **Recommended**: `notes` (match reasoning, seniority judgment)

The wrapper hard-rejects: missing URL, invalid URL format, missing required fields.

## Accepted Evidence Paths

**Path A: Web Search → Web Fetch → Log**
```
web_search → extract specific job posting URL → web_fetch (confirm real JD) → career_log_candidates
```

**Path B: Targeted ATS → career_fetch_source → Log**
```
web_search("site:boards.greenhouse.io <keywords>") → extract ATS job URL → career_fetch_source → confirm from returned text → career_log_candidates
```

**Path C: Career Page Snowball → Log**
```
web_fetch(company listing page) → extract detail URLs → web_fetch(each detail URL) → career_log_candidates
```

Every candidate must trace back to one of these paths.

## Platform Provenance Gate (what happens after you finish)

- `tool_events.jsonl` missing or HMAC invalid → `ToolLedgerValidator` fails → `needs_review`
- `candidate_count > 0` but no `candidate_log` event in ledger → `DiscoveryEvidenceValidator` fails
- `candidate_pool` hash mismatch with ledger → data tampering detected → fails

## Coverage Report Format

Write to `payload.output_paths.coverage_report_path` before calling `career_write_manifest`:

```markdown
# Coverage Report
## Summary
- Candidates logged: <N>
- Queries run: <N>
- Sources tried: <list>
## What Worked
<which moves/sources produced candidates>
## Gaps
<which directions had no results and why>
## Recommended Next
<what the next run should try>
```
