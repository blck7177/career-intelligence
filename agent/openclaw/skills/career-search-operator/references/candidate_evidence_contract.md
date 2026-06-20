# Candidate Evidence Contract（最硬的操作规则）

这是本 skill 里**最不可妥协**的部分。平台用真实 tool-call 做反捏造校验，违反会导致候选被拒或整个 run 中止。

## 目录
- [入池必要条件](#入池必要条件)
- [Accepted Evidence Paths](#accepted-evidence-paths)
- [工具机制](#工具机制)
- [Platform Provenance Gate](#platform-provenance-gate)
- [Coverage Report 格式](#coverage-report-格式)

---

## 入池必要条件（全部满足才能 `career_log_candidates`）

1. **URL 是真实 job posting URL**：
   - 不是搜索结果页（`google.com/search?q=...`、`linkedin.com/jobs/search?...`）
   - 不是公司主页 / about 页
   - 不是 career listing 页（listing 页上的具体岗位 URL 才是候选）
2. 已经有 evidence（来自 web_fetch 确认、或 board_sync 直接出候选）
3. 必填字段：`url`（非空真实 URL）、`title`、`company`
4. 建议字段：`location`、`relevance`（`relevant` / `maybe`，默认 maybe）、`reason`、`workstream_hint`

工具会硬拒（记入 `skipped_results.jsonl`）：
- 无真实 URL → `rejected_no_url`
- URL 是搜索结果/listing 页 → `rejected_search_page`

---

## Accepted Evidence Paths（候选必须来自其中一条）

**Path A: Web Search → Web Fetch（发现新公司）**
```
web_search
  → career_search_session log-query   （每次 web_search 必做）
  → web_fetch（逐个候选 URL 确认）
  → career_log_candidates
```

**Path B: Board Sync（已知 ATS 公司）**
```
career_sync_board
  → connector 直接写候选到 candidate_pool.jsonl
  → （无需额外 career_log_candidates，board sync 自动完成）
```

**Path C: Source Discovery → Board Sync（发现新 ATS）**
```
web_search / web_fetch（发现公司 ATS board URL）
  → career_classify_source
  → career_register_board
  → career_sync_board
  → connector 写候选
```

**Path D: Career Page Snowball（HTML 公司）**
```
web_fetch（公司 career listing 页）
  → 从页面提取具体岗位 URL
  → web_fetch（每个 detail URL 确认）
  → career_log_candidates
```

> **每条候选必须追溯到以上某条 evidence path。**
> 平台入库 gate 会验证 discovery action 是否真实存在。

---

## 工具机制（不是策略，是机制）

- **写文件用 write tool**（写 query JSON、候选草稿、coverage report）。
- **exec 只用于 `./wrappers/*`**（使用完整路径 `./wrappers/career_search_session`，或工作目录相对路径）。
- **绝不**用 `exec python3 -c "..."` 或 heredoc 内联脚本——exec allowlist 只允许 wrappers。
- **搜索只用 `web_search` 工具**；绝不用 `web_fetch` 抓 `google.com/search?...` 等搜索结果页代替。

---

## Platform Provenance Gate（你不需要实现，但需要知道）

**Tool 层（`career_log_candidates` 内置）：**
- `candidate_pool` 为空（`queries_run=0` 且无 board sync）时拒绝候选

**Run 层（worker 执行）：**
- 无任何 discovery action（web_search + board_sync + classify_source 全为 0）→ `SearchValidationError`，run 中止
- 有 discovery action 但 0 候选 → valid no-yield run，正常进入 pipeline（空 pool）
- 候选存在但无 evidence path → pipeline admission gate 拒绝那些候选

---

## Coverage Report 格式（run 结束前必须写）

写到 spec 的 `expected_output_paths.coverage_report` 路径：

```markdown
# Coverage Report — Session <session_id>

## Discovery Summary
- Session: <session_id>
- Discovery actions: web_search N queries, board_sync N companies, classify_source N
- Total candidates logged: N
  - Via board_sync: N
  - Via web_search + web_fetch: N
- Relevant: N / Maybe: N / Rejected: N

## Search Coverage
- Workstreams targeted: （列出覆盖的 workstream）
- Source types used: （company_career_page / ats_board / aggregator）
- Companies / boards attempted: （列出尝试过的公司）

## What Worked
（哪些 move / source 产出了真实候选？）

## What Failed / Coverage Gaps
（哪些方向无结果？failure mode？还缺哪些 workstream / company？）

## New Sources Discovered
（发现了哪些新 ATS board，是否注册？）

## Recommended Next Direction
（下一次 run 应该优先补充什么？）
```
