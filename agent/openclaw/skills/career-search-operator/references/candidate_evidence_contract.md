# Candidate Evidence Contract（最硬的操作规则）

这是本 skill 里**最不可妥协**的部分。平台用 `tool_events.jsonl` 里的 HMAC 签名 ledger 做反捏造校验，违反会导致整个 run 进入 `needs_review`。

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
2. 已经有 evidence（来自 `web_fetch` 或 `career_fetch_source` 确认真实 JD 内容）
3. 必填字段：`url`（非空真实 URL）、`title`、`company`、`source_type`
4. 建议字段：`notes`（匹配原因、seniority 判断等）

wrapper 会硬拒（记入 `errors` 列表并跳过）：
- 无真实 URL → `url must start with http:// or https://`
- 缺少必填字段 → `Missing fields: {...}`

---

## Accepted Evidence Paths（候选必须来自其中一条）

**Path A: Web Search → Web Fetch → Log**

```
web_search("<role keywords> <location>")
  → 从结果中提取具体 job posting URL（不是搜索结果页本身）
  → web_fetch（确认是真实 JD 页面，有 title / responsibilities / requirements）
  → career_log_candidates
```

**Path B: Targeted ATS Search → career_fetch_source → Log**

```
web_search("site:boards.greenhouse.io <keywords>")
  OR web_search("site:jobs.lever.co <keywords>")
  OR web_search("site:jobs.ashbyhq.com <keywords>")
  → 提取具体 ATS job URL（如 greenhouse.io/<company>/jobs/<id>）
  → career_fetch_source（fetch + normalize，返回 text 内容）
  → 用 text 确认真实 JD 后 → career_log_candidates
```

**Path C: Career Page Snowball → Log**

```
web_fetch（公司 career listing 页）
  → 从页面内容提取具体岗位 detail URL
  → web_fetch（每个 detail URL，确认真实 JD 内容）
  → career_log_candidates
```

> **每条候选必须追溯到以上某条 evidence path。**
> 平台 Validator Gate 会检查 `tool_events.jsonl` 里是否存在有效的 signed `candidate_log` event。

---

## 工具机制（不是策略，是机制）

- **所有 wrapper 统一通过 `--task-spec <json文件> --output <json文件>` 调用。** 不使用旧的 `--session-id`、`--workspace-id`、`--url` 等独立 flag。
- **exec 只用于 allowlist 内的 wrapper**，调用格式：
  ```
  tool: exec
  name: career_log_candidates
  args:
    --task-spec /tmp/spec.json
    --output /tmp/result.json
  ```
- **绝不**用 `exec python3 -c "..."` 或 heredoc 内联脚本——exec allowlist 只允许指定的 4 个 wrapper。
- **搜索只用 `web_search` 工具**；绝不用 `web_fetch` 抓 `google.com/search?...` 等搜索结果页代替搜索。
- **写临时 spec 文件用 write tool**（写候选列表 JSON、fetch_source spec 等）。

---

## Platform Provenance Gate（你不需要实现，但需要知道）

**Wrapper 层（`career_log_candidates` 内置）：**
- 每条候选验证 `url`、`title`、`company`、`source_type` 必填
- URL 格式验证（必须 `http://` 或 `https://` 开头）
- 写入 `output_paths.tool_events_path` 所指的 HMAC 签名 ledger（`tool_events.jsonl`）

**Run 层（worker 执行 Validator Gate）：**
- `manifest schema 不合法 / artifact 文件缺失` → `SchemaValidator` / `ProvenanceValidator` 失败
- `tool_events.jsonl` 不存在 或 HMAC 签名/hash chain 无效 → `ToolLedgerValidator` 失败，task → `needs_review`
- `candidate_count == 0` → `DiscoveryEvidenceValidator` 失败（0-result run 在 v1 没有 signed search proof），task → `needs_review`
- `candidate_count > 0` 但 ledger 里没有 `candidate_log` event，或 `candidate_count` 与 pool 实际行数不匹配 → `DiscoveryEvidenceValidator` 失败，task → `needs_review`
- manifest 声明的 `candidate_count` 与 pool 实际行数不一致 → `DiscoveryCountValidator` 失败

---

## Coverage Report 格式（run 结束前必须写）

写到 `payload.output_paths.coverage_report_path`：

```markdown
# Coverage Report — Run <run_id> / Task <task_id>

## Discovery Summary
- Run ID: <run_id>
- Task ID: <task_id>
- Discovery actions: web_search <N> queries, web_fetch <N> pages, career_fetch_source <N> fetches
- Total candidates logged: <N>
  - Via web_search + web_fetch: <N>
  - Via targeted ATS search + career_fetch_source: <N>
  - Via career page snowball: <N>

## Search Coverage
- Role families targeted: （列出 payload.discovery_intent.target_role_families 里的 name）
- Expansion scope: <narrow | standard>
- Source types used: （greenhouse / lever / ashby / company_career_page / aggregator）
- Companies / pages attempted: （列出尝试过的公司或 URL 前缀）

## What Worked
（哪些 move / source 产出了真实候选？具体 query 模式、site: 前缀等）

## What Failed / Coverage Gaps
（哪些方向无结果？failure mode？login wall / bot blocked / no results / irrelevant results？）
（还缺哪些 role families / companies？）

## Recommended Next Direction
（下一次 run 应该优先补充什么？换哪个 source？用什么 query 模式？）
```
