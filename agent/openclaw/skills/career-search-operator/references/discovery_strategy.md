# Discovery Strategy & Moves

## Goal-Driven, Not Step-Driven

You own the **discovery objective** — maximize validated candidate supply within budget — not a fixed query sequence.

`budget.max_candidates` is your **target, not just a ceiling**. Do not stop early because you found a few strong matches. Keep searching until you approach this target or exhaust your tool call budget.

Your plan is temporary. Revise it based on evidence: search results, fetched pages, missing candidates, irrelevant results, source limitations.

Continuously distinguish:
- **action completion**: ran a query, fetched a page
- **objective progress**: found relevant real job candidates
- **strategy failure**: actions running but objective not advancing

**Optimize objective progress, not tool call count.**

## Before You Start

Read `catalog_context` and `previous_run_diagnostics` from the task spec:
- `known_roles` — jobs already discovered. Do not re-log.
- `recently_seen_companies` — deprioritize, explore new sources.
- `last_run_errors` — fix whatever went wrong last time.
- `coverage_gaps` — prioritize these directions.
- `key_learnings` — known pitfalls in this search space.

**Read context first, then plan. Never start from scratch.**

### Known Boards — Use Them First

Before broad web searches, iterate through `source_registry_snapshot.known_boards`. These are confirmed ATS boards with structured job listings — the highest-yield source. For each board, do a targeted search for roles matching `target_role_families`.

## You May Freely Change

Query family, source strategy, target companies, terminology, relevance criteria, exploration depth, move type.

## You May Not Change

- Data boundaries (see `data_policy_summary.md`)
- Evidence requirements (see `candidate_evidence_contract.md`)
- Tool mechanism: search only via `web_search` tool, never `web_fetch` on search engine result pages

---

## Discovery Moves

These moves can be **freely combined in any order**. Choose based on `payload.discovery_intent` and current discovery state.

### Move 1: Direct Web Search

Best for: exploring new companies, new directions.

```
web_search("<role keywords> <location> jobs")
  → extract specific job posting URLs from results
  → web_fetch each candidate URL to confirm real JD content
  → career_log_candidates
```

### Move 2: Targeted ATS Search

Best for: known ATS platforms (Greenhouse / Lever / Ashby).

```
web_search("site:boards.greenhouse.io <role keywords>")
  → extract specific ATS job URLs (e.g. greenhouse.io/<company>/jobs/<id>)
  → career_fetch_source (fetch + normalize)
  → confirm real JD from returned text → career_log_candidates
```

**If `career_fetch_source` fails for a URL:**
1. Try `web_fetch` on the same URL as fallback.
2. If the URL itself is bad (403/404), try other jobs from the same ATS board.
3. Do NOT stop the search because one fetch failed — move to the next source.

### Move 3: Career Page Snowball

Best for: companies with custom HTML career pages.

```
web_fetch(<company>/careers or /jobs listing page)
  → extract specific job detail URLs from page content
  → web_fetch each detail URL to confirm real JD content
  → career_log_candidates
```

Key: listing pages are not candidates. Only specific job detail URLs qualify.

### Move 4: Source Pivot

Trigger when: current source/query direction yields nothing (403, login wall, irrelevant results).

- LinkedIn/Indeed login wall → switch to `site:boards.greenhouse.io` targeted search
- Workday blocked → try company career page (Move 3)
- Too-broad platform results → add `site:` prefix for targeted ATS search
- No results for a keyword → try other families from `target_role_families`

Document every pivot reason in coverage_report.

### Move Selection Guide

| Scenario | Preferred Move |
|----------|---------------|
| Exploring new companies / directions | Move 1: Direct Web Search |
| Known Greenhouse / Lever / Ashby ATS | Move 2: Targeted ATS Search |
| Company has custom career page | Move 3: Career Page Snowball |
| Current source blocked / no results | Move 4: Source Pivot |
| Budget almost exhausted | Focus on highest-yield known direction |

### Minimum Coverage Before Stopping

- At least 3 distinct search query families (different role titles or ATS platforms).
- At least 50% of `known_boards` checked for relevant roles.
- At least 1 open web search (not site-constrained) to discover new companies.

---

## Self-Review Every 5 Actions

**MANDATORY**: After every 5 tool calls, call `career_search_status`. Check the response:
- If `budget_remaining.candidates` > 10, you **MUST** continue searching.
- If `budget_remaining.tool_calls` ≤ 2, wrap up with the best candidates found so far.

Answer briefly (1-2 sentences each):

1. What was I looking for in these 5 actions?
2. How many real candidates did I find? How many remain vs `budget.max_candidates`?
3. What didn't work? Why?
4. What role categories / companies / sources are still uncovered?
5. Next: continue, expand, or pivot? Why?

## Stop Conditions (any one triggers)

1. Candidate count approaches `budget.max_candidates` (within 80% of target).
2. All `known_boards` checked AND ≥3 distinct web search query families exhausted with no new results.
3. ≥3 consecutive strategy adjustments with 0 new candidates — document gap, finish.
4. Budget exhausted (`max_tool_calls` reached).

Do NOT stop just because you found a few strong matches. The user selected this budget because they want comprehensive coverage.

After stopping → write `coverage_report.md` → call `career_write_manifest` → STOP.
