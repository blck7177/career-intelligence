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

### Known Boards — Greenhouse/Lever/Ashby Are Already Synced. Don't Re-Search Them.

Before this run started, the platform already pulled every **Greenhouse, Lever, and Ashby** board in `source_registry_snapshot.known_boards` directly from that ATS's structured JSON API — for free, with zero tool calls from you. Any jobs on those boards are already in the catalog (see `catalog_context.known_roles`). Do **NOT** spend `web_search`, `web_fetch`, or `career_fetch_source` calls re-discovering or re-confirming jobs on a `known_boards` URL that contains `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co`, or `jobs.ashbyhq.com` — that work is already done and burns budget for zero new data.

**Workday and other non-API-synced boards are different.** `known_boards` entries on `myworkdayjobs.com`, a company's own Workday-hosted domain, or any other platform are **not** auto-synced — there is no free API pull for those. For those boards, manual search/fetch (Move 1–3) is still the right and necessary approach.

So: treat the Greenhouse/Lever/Ashby subset of `known_boards` as a **negative list** — companies to skip. Treat the rest of `known_boards` (Workday, custom career sites) as you always have — legitimate manual-search targets, just deprioritized vs. brand-new companies. Your highest-value use of budget is finding companies/boards **not on `known_boards` at all** (growing the registry — see `budget.max_new_sources`), not re-walking the Greenhouse/Lever/Ashby names you already have.

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

### Move 2: Targeted ATS Search (New Companies Only)

Best for: a company you suspect is on Greenhouse / Lever / Ashby but whose board is **not yet** in `source_registry_snapshot.known_boards`.

```
web_search("site:boards.greenhouse.io <role keywords>")
  → extract specific ATS job URLs for companies NOT already in known_boards
  → career_fetch_source (fetch + normalize)
  → confirm real JD from returned text → career_log_candidates
```

Do not run this move against a Greenhouse/Lever/Ashby company already present in `known_boards` — it was already synced automatically before this run started (see "Known Boards" above). If a URL you find turns out to belong to a company already in `known_boards`, skip it and move on — don't fetch/log it.

**If the result has `"note"` mentioning the ATS structured API:** the text you got back is a short excerpt, not the full posting — that's expected. Realness is already confirmed by the ATS API itself (this is a live entry in that company's board, not a scrape you have to sanity-check), so don't reject it or ask for more text on realness grounds. Just judge relevance/seniority from the excerpt and log it if it fits, same as any other candidate.

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
| Suspected Greenhouse / Lever / Ashby company NOT in `known_boards` | Move 2: Targeted ATS Search |
| Company already in `known_boards` (Greenhouse/Lever/Ashby) | Skip — already synced, do not search |
| Company has custom career page | Move 3: Career Page Snowball |
| Current source blocked / no results | Move 4: Source Pivot |
| Budget almost exhausted | Focus on highest-yield known direction |

### Minimum Coverage Before Stopping

- At least 3 distinct search query families (different role titles or platforms), targeting companies **not** already in `known_boards`.
- At least 1 open web search (not site-constrained) to discover new companies.
- Real progress toward `budget.max_new_sources`: keep looking for boards/companies outside `known_boards` until you hit that cap or run low on `max_tool_calls`. Do not stop early just because you've "covered" `known_boards` — the Greenhouse/Lever/Ashby names on it required zero search effort from you, so covering them isn't evidence of real progress.

---

## Self-Review Every 5 Actions

**MANDATORY**: After every 5 tool calls, call `career_search_status`. Its response already gives you `candidates_logged`, `tool_calls_used`, and `budget_remaining` — use those numbers directly, do not re-derive or narrate them.

Pick exactly ONE and act on it immediately. No free-text reflection needed here — save prose for `coverage_report.md` at the end of the run.

- **`continue`** — `budget_remaining.candidates` > 10 and your current move is still producing new candidates → keep going with the same query family / source.
- **`expand`** — your current move has stalled (0–1 new candidates in the last 5 actions) → switch move or query family (see Move Selection Guide) toward a company/source not yet tried.
- **`wrap_up`** — `budget_remaining.tool_calls` ≤ 2, or `budget_remaining.candidates` ≤ 0, or this is your 3rd consecutive stalled checkpoint → stop, write `coverage_report.md`, call `career_write_manifest`.

If you pick `expand` or `wrap_up`, keep a one-line note of why — it goes into `coverage_report.md`'s Gaps/Recommended-Next sections at the end, not into the checkpoint itself.

## Stop Conditions (any one triggers)

1. Candidate count approaches `budget.max_candidates` (within 80% of target).
2. ≥3 distinct web search query families exhausted with no new results, and new-source discovery has plateaued (your last 2 pivots found no company outside `known_boards`).
3. ≥3 consecutive strategy adjustments with 0 new candidates — document gap, finish.
4. Budget exhausted (`max_tool_calls` reached).

Do NOT stop just because you found a few strong matches. The user selected this budget because they want comprehensive coverage.

After stopping → write `coverage_report.md` → call `career_write_manifest` → STOP.
