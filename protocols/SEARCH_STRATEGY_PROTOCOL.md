# Search Strategy Protocol

> ⚠️ **适用范围**：本文档是 **legacy / 手动 `career-intel` monolith** 的**全流程**搜索策略文档，
> 含 session 生命周期（`career_search_session start`/`end`）、`board_sync`、source routing、
> 把 `coverage_report.md` 写到 `agent_work/drafts/` 等内容——这些 **不适用** 生产的 bounded
> `career-search-agent`。
>
> 生产 bounded search turn **不读本文件**，改读 self-contained skill 包：
> `skills/career-search-turn-operator/SKILL.md` + 其 `references/`（`search_turn_io.md` /
> `search_strategy.md` / `candidate_admission_gate.md` / `coverage_draft_template.md` /
> `data_policy_summary.md`）。本文件保留为 legacy 参考与策略思想的全量背景。

Search is an agent-led research loop. You own the objective, not the steps.

---

## Search Autonomy Mandate

You are responsible for achieving the search objective — discovering relevant job candidates — not merely executing queries.

Your search plan is provisional. You may revise it at any time based on evidence from search results, fetched pages, missing candidates, irrelevant results, duplicate results, source limitations, or newly discovered terminology.

Continuously distinguish between:
- **action completion**: a query was run, a page was fetched
- **objective progress**: useful candidate jobs were discovered
- **strategy failure**: actions are being completed but not advancing the objective

When objective progress is weak, do not assume the market has no relevant jobs. First examine whether your current search method, source choice, query language, result interpretation, or triage standard is the problem.

You may freely change query families, source strategy, company targets, terminology, relevance criteria, and exploration depth. The only things you may not change are the boundaries in `DATA_POLICY.md` and the logging requirements below.

---

## Boundaries（不可跨越）

**Hard constraints — always hold:**
- 不能登录平台、不能绕过 paywall
- 不能直接写 db（必须通过 career_run_discovery）
- 不能跳过 validation 步骤
- 所有候选必须有真实 source_url（通过 web_fetch 确认，不是搜索摘要推断）
- source 限制见 DATA_POLICY.md

**Logging requirements — audit trail:**
- 每次 web_search 之后必须调用 `career_search_session log-query` 记录 query 和结果摘要
- 每个入池候选必须通过 `career_log_candidates` 记录（不能直接写文件绕过）
- session 结束前必须写 coverage_report.md 并调用 `career_search_session end`

---

## Tool Mechanics（工具如何工作的事实）

**web_search → web_fetch 是两步，不是一步：**
- `web_search` 返回的是搜索摘要和 URL 列表，不是 job posting 本身
- 必须从搜索结果里提取每个具体 URL，再对每个 URL 单独调用 `web_fetch`
- `google.com/search?q=...` 这类搜索结果页 URL 本身不是候选，不要把它写进 candidate

**写文件用 write tool，不用 exec：**
- 创建 JSON、markdown 等文件用文件 write tool（不需要 exec 权限）
- exec tool 只用于调用 `./wrappers/` 下的脚本
- 不要用 `exec python3 -c "..."` 或 heredoc 内联脚本写文件，会被 allowlist 拒绝

**`career_search_session log-query` 的正确两步模式：**

```
# Step 1：用 write tool 写 query JSON 文件
write agent_work/drafts/query_01.json:
{
  "query_text": "<actual query text>",
  "search_intent": "<describe search intent>",
  "query_type": "targeted_site_search",
  "query_family": "<derived from profile keywords>",
  "source_type": "company_career_page",
  "results_seen": [
    {"title": "<job title>", "url": "<job posting url>", "relevance": "relevant"}
  ],
  "valid_url_count": 1,
  "candidate_yield": 1,
  "observed_failure_mode": "none"
}

# Step 2：exec 调用 wrapper
exec: ./wrappers/career_search_session log-query --session-id <id> --query-file agent_work/drafts/query_01.json
```

**Observability fields（每次 log-query 时填写）：**

| 字段 | 填什么 | 可选值 |
|---|---|---|
| `source_type` | 这次搜索的 source 类型 | `company_career_page` / `ats_board` / `aggregator` / `recruiter_post` / `unknown` |
| `valid_url_count` | 结果里真实 JD URL 的数量（排除搜索结果页） | int |
| `candidate_yield` | 本次 query 实际加入 candidate_pool 的条数 | int |
| `observed_failure_mode` | 观测到的失败模式 | `none` / `blocked_403` / `no_results` / `fake_urls` / `search_result_pages_only` / `other` |

如果不填，系统会自动填入默认值（`unknown` / `none` / `null`），但填写后 strategy review 质量更高。

**`career_log_candidates` 的字段和调用方式：**

单条调用：
```
exec: ./wrappers/career_log_candidates \
  --session-id <id> \
  --url "<job posting url>" \
  --title "<job title>" \
  --company "<company name>" \
  --location "<location>" \
  --relevance relevant \
  --reason "<reason this posting matches the profile>" \
  --role-category-hint "<role category from taxonomy>"
```

批量调用（先 write tool 写文件，再 exec）：
```
# Step 1：write tool 写 candidates JSON
write agent_work/drafts/candidates_batch.json:
[
  {
    "url": "<job posting url>",
    "title": "<job title>",
    "company": "<company name>",
    "location": "<location>",
    "relevance": "relevant",
    "relevance_reason": "<reason this posting matches the profile>",
    "role_category_hint": "<role category from taxonomy>"
  }
]

# Step 2：exec 调用 wrapper
exec: ./wrappers/career_log_candidates --session-id <id> --candidates-file agent_work/drafts/candidates_batch.json
```

必填字段：`url`（必须是真实 job posting URL，不能为空）、`title`、`company`
注意：字段名是 `url`，不是 `source_url`（`source_url` 也被接受，但 `url` 是标准名）
可选字段：`location`、`relevance`（relevant/maybe，默认 maybe）、`reason`、`role-category-hint`

---

## Session 生命周期

**开始：**
调用 `./wrappers/career_search_session start --profile <name>`，然后在 `agent_work/drafts/strategy_state.md` 里写下初始策略状态（见下方模板）。

**过程中：**
随时更新 `strategy_state.md`。每次 web_search 后调用 `career_search_session log-query`。每 5 次 query 后调用 `career_search_status`，然后做一次 **Strategy Review**（见下方模板），自己判断是否需要调整策略，并把结论写回 `strategy_state.md`。

**结束：**
按下方固定格式写 `agent_work/drafts/coverage_report.md`，调用 `./wrappers/career_search_session end`。

---

## Strategy Review Block（每 5 次 query 后必做）

每 5 次 query 后，基于 `career_search_status` 的输出，在 `strategy_state.md` 里回答以下 7 个问题。
不需要长篇大论——每条 1-2 句话即可。这是给自己的工作记录，不是给用户的汇报。

```markdown
## Strategy Review — Query Block N (q_XXX – q_YYY)

1. Search objective this block
   （这 5 次 query 想找什么？）

2. Queries tried
   （搜了哪几个方向 / source？）

3. Valid candidates found
   （找到几个真实 JD URL？加入 candidate_pool 几条？）

4. Failure modes observed
   （有哪些 query 没效果？原因是什么？blocked_403 / no_results / fake_urls / search_result_pages_only？）

5. Coverage gap
   （还缺哪些 role category / company group / source type 没覆盖？）

6. Strategy change, if any
   （下一步是继续、扩展、还是切换方向？为什么？）

7. Next query directions
   （接下来具体搜什么？）
```

---

## Strategy State（live research notebook）

在 `agent_work/drafts/strategy_state.md` 维护以下结构，随时修改：

```markdown
# Strategy State
Session: <session_id>

## Current Objective
（本次 run 要发现什么类型的岗位）

## Current Working Hypothesis
（我认为哪些 source / query 最有可能找到目标岗位）

## What I Have Learned
（已观测到的：哪些 query 有效，哪些 source 有结果，哪些 URL 是真实 JD）

## What Seems Not To Be Working
（哪些方向效果差，为什么）

## Current Strategy Revision
（基于上面的观测，我现在的搜索方向是什么）

## Next Move
（下一步具体做什么）
```

这个文件不是汇报给用户的，是你的外部工作记忆。你可以在任何时候修改它。

---

## Search Moves（可自由组合，不是固定顺序）

- **board_sync**（优先）: 对 Greenhouse / Lever / Ashby 公司直接调用 `career_sync_board`，一次性获取全部 published jobs。比 HTML fetch 稳定，无 bot 保护问题。先查 `configs/company_boards.yaml` 确认 board profile，再执行：
  ```
  exec: ./wrappers/career_sync_board --source <ats_type> --slug <company_slug> --session-id <id>
  ```
- **targeted_site_search**: `site:<company_career_page> <keyword> <location>`（适合不在 boards 里的公司）
- **broad_keyword_search**: 通用关键词 + location + seniority
- **company_career_page_snowball**: web_fetch 公司 career page，从页面上找相关岗位列表
- **query_expansion**: 从 JD 内容里发现新术语，生成新 query
- **source_pivot**: 切换到不同平台（LinkedIn public / Indeed / 公司官网）

---

## Source Routing（connector 决策树）

发现一个候选 URL 后，在 web_fetch 之前，先判断来源：

1. 先调用 `career_classify_source --url <url>` 查看 `source_type`
2. 根据 `source_type` 决定策略：

| source_type | 策略 |
|---|---|
| `greenhouse` | 不需要手动 fetch；`career_run_discovery` 会自动走 Greenhouse API |
| `lever` | 同上，自动走 Lever API |
| `ashby` | 同上，自动走 Ashby API |
| `workday` | 预计失败率高；优先用 `search_aggregator`（LinkedIn/Indeed）发现岗位，不要直接 fetch detail page |
| `html` | 正常 web_fetch 验证，再 log_candidates |

3. 对于 Greenhouse / Lever / Ashby 的公司：直接用 `board_sync` 而不是逐 URL fetch，效率更高。

**不再推荐** `site:greenhouse.io` 等搜索 query——改为"发现 company → 查 `configs/company_boards.yaml` → 走 connector"。

---

## Coverage Report Template（session 结束前必须按此格式写）

把这个模板写入 `agent_work/drafts/coverage_report.md`，然后调用 `career_search_session end`。
不要自由发挥格式——固定 section 名称和结构，方便 run summary 索引。

```markdown
# Coverage Report — Session <session_id>

## Search Coverage
- Role categories searched: （列出覆盖的 role category）
- Source types used: （列出 company_career_page / ats_board / aggregator 等）
- Company groups targeted: （列出尝试过的公司或公司类型）
- Queries run: N

## What Worked
（哪些 query / source 产出了真实 JD candidates？）

## What Failed
（哪些方向无结果？具体 failure mode 是什么？blocked_403 / no_results / fake_urls / search_result_pages_only）

## Coverage Gaps
（还缺哪些 role category / company group 没有足够候选？）

## Candidates Summary
- Total candidates logged: N
- Relevant: N
- Maybe relevant: N
- Rejected (no URL / invalid): N

## Recommended Next Search Direction
（下一次 run 应该优先补充什么？）
```

---

## Stop Conditions（agent 自主判断）

以下任一满足时考虑结束 session：
1. 目标候选数量已达到
2. 所有主要 source families 都已覆盖
3. 连续 ≥3 次策略修改后仍然 0 新候选——记录 gap，结束
4. 达到 search budget（30 queries / 40 fetched pages）

**进入 pipeline 的 candidate quality gate：**

candidate_pool 里的每一条 candidate 在送入 pipeline 前应满足：
- `url`：真实 job posting URL（非搜索结果页、非公司主页）
- `title` + `company`：非空
- `relevance_reason`：说明为什么认为这个岗位相关
- `role_category_hint`：对 role category 的初判（可以是 "unknown"，但不能缺失）

不需要要求覆盖所有 role category，也不要求零失败率。candidate_pool 质量可接受即可进入 pipeline。
