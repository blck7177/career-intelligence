# Discovery Run — I/O Contract

```
Worker owns lifecycle, session, persistence, and ingestion gate.
Agent owns discovery strategy inside the run budget.
Service owns canonical database.
```

## 输入：读 task spec 文件

平台在你的 prompt 里给一个 task spec 文件路径。用 read tool 读它：

```json
{
  "session_id": "<YYYY-MM-DD_HHMMSS>",
  "workspace_id": "<workspace_id>",
  "search_request": {
    "raw_user_request": "找 market risk / valuation control 相关岗位",
    "profile_name": "market_risk_nyc",
    "profile_summary": "...",
    "discovery_intent": {}
  },
  "catalog_context": {
    "existing_job_count": 12,
    "recent_companies": ["<company_A>", "<company_B>"]
  },
  "strategy_context": {
    "coverage_gaps": ["buy-side risk", "Ashby-board companies"],
    "effective_sources": ["<ats_domain>/<company_slug>", "<ats_domain>/<company_slug>"],
    "avoid_sources": ["<domain> — login-required", "<domain> — bot-blocked"],
    "effective_query_patterns": ["site:<ats_domain> <role_keywords> <location>"],
    "avoid_query_patterns": ["<broad_query> — returns aggregator pages only"],
    "key_learnings": ["<company> board_sync filter too narrow; broaden to '<adjacent_keywords>'"],
    "recommended_next_searches": ["Retry <company> board_sync with broader title_keywords", "Expand to <source_type> for <workstream> workstream"]
  },
  "source_context": {
    "company_boards_path": "configs/company_boards.yaml",
    "source_policy_path": "configs/source_policy.yaml"
  },
  "budget": {
    "max_queries": 30,
    "max_pages": 40,
    "max_board_syncs": 10
  },
  "expected_output_paths": {
    "coverage_report": ".../runs/<session_id>/coverage_report.md",
    "discovery_notes": ".../runs/<session_id>/discovery_notes.md"
  }
}
```

`search_request.discovery_intent` 为空 `{}` 时：按 legacy 模式执行，用 `raw_user_request` + `profile_name` + `strategy_context` 自主决定策略。  
`search_request.discovery_intent` 非空时：见下方 **"Executing with discovery_intent"** 节。

后续所有 wrapper 调用都必须同时带上 `--session-id <session_id>` **和** `--workspace-id <workspace_id>`。

### `strategy_context` 字段说明

`strategy_context` 是跨 run 积累的策略经验，由每轮 reflect 后的 `apply_strategy_patch` 写入。**这是你避免重复失败的核心工具**——首轮 run 时各字段为空是正常的。

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `coverage_gaps` | 上轮 reflect 判定为 weak/missing 的 workstream | 优先把 budget 倾向这些方向 |
| `effective_sources` | 历史上成功 fetch 到 JD 的 source | 优先选用 board_sync 或 `site:` 搜索 |
| `avoid_sources` | 历史上系统性失败的 source（含 reason） | 跳过，不浪费 budget |
| `effective_query_patterns` | 产出过真实 JD URL 的 query 模式 | 参考用于 web_search |
| `avoid_query_patterns` | 只返回聚合器/搜索结果页的 query 模式 | 不重复使用 |
| `key_learnings` | 历史 run 的关键发现（最近 8 条） | 理解系统对这个搜索方向已知道什么 |
| `recommended_next_searches` | 上轮 reflect 推荐的下一步方向（最多 5 条） | 作为本轮起始策略参考，但你可以调整 |

## 平台在你之前已做完的事

- `start_session` 已创建 run 目录 + `run_config.yaml`（含 `search_budget`）。
- **session 已存在**——你只需 `career_search_status` 确认，**绝不** `career_search_session start`。
- `catalog_context` 和 `strategy_context` 里的信息已由平台注入：你无需重新查询 job database 或 strategy state。

## 你负责产出的内容

**必须产出：**
- `coverage_report.md`（写到 spec 的 `expected_output_paths.coverage_report` 路径）

**可选但鼓励：**
- `discovery_notes.md`（新发现的 source、策略观察、推荐下轮方向）
- `candidate_pool.jsonl` 增量由 `career_log_candidates` wrapper 自动写入，你不需要手写

## 平台在你之后会做的事（你不要碰）

1. **Discovery action 校验**：检查 run log 里是否有真实 discovery action（web_search / board_sync / classify_source）。无任何 discovery action → run 以 `SearchValidationError` 中止。有 action 但无候选 → valid no-yield run，正常进入 pipeline（空 pool）。
2. **`end_session`**：把你的 `coverage_report.md` 登记到 run 目录，置 `search_complete`。
3. **`run_processing_pipeline`**：`candidate_pool.jsonl` → fetch/extract/classify/validate → 结构化入库。
4. **Reflect turn**：驱动 `career-reflect-agent` 更新 strategy state。

## Executing with discovery_intent

当 `search_request.discovery_intent` 非空（有 `intent_kind` 和 `search_lanes`），把它当作 **search contract**。

### 核心规则

**1. Intent Translator decides what to search. You decide how to search.**

`discovery_intent` 里的 lanes 告诉你搜什么方向、分多少 budget、哪些关键词是起点。  
你仍然自主决定：查哪些 source、怎么扩展 query、怎么处理 board_sync failure、遇到 bot-block 时如何 pivot。

**2. Budget 按 lane 分配**

每个 lane 有 `budget_share`（0–1，所有 lane 合计为 1.0）。用它按比例分配 `budget.max_queries`：

```
lane_queries = round(budget.max_queries * lane.budget_share)
```

Budget 执行中可以小幅调整（±1-2 query），但不应大幅偏离 `budget_share` 比例。

**3. 不覆盖 hard constraints**

`global_constraints.hard_constraints` 和 `lane.inherited_hard_constraints` 是强制约束：

- `max_years_experience: 3` → 不把 5-7 年经验的岗位加进 candidate pool
- `location: NYC only` → 不搜外地岗位
- `exclude: model_validation` → query seeds 里不加 model validation 主关键词

**4. Query seeds 可以扩展，但必须保持 lane 语义**

`lane.query_seeds` 是起点，你可以：
- 添加 `site:<ats_domain>` 前缀
- 加 location qualifier（"NYC", "New York"）
- 组合两个 seed 词

但不要把 `exposure_management` lane 的 query 扩展成 `stress testing model validation`——那是另一个 lane 的语义。

**5. 每个 logged candidate 标记 lane_id**

用 `career_log_candidates` 时，在 candidates 的 `metadata` 字段（如果 wrapper 支持）里记录 `lane_id`。  
如果 wrapper 不支持 metadata，在 `discovery_notes.md` 里记录每个 lane 产出了哪些 candidates。

**6. Lane exhausted → 记录，不随意换方向**

一个 lane 用完预算仍然零 yield → 在 `coverage_report.md` 里标记：

```
lane: exposure_management — exhausted (3 queries, 0 candidates, sources: X/Y/Z)
```

不要把这个 lane 的剩余 budget 随意挪给另一个方向。如果你有充分理由换 lane 策略，在 `discovery_notes.md` 里说明原因。

**7. 空 discovery_intent → 回退到 legacy 模式**

`discovery_intent` 为空 `{}` 或缺失时，完全忽略本节规则，回退到自主 strategy 模式（参考 `discovery_moves.md`）。

---

## Executing with attempt_context (multi-attempt runs)

当 `search_request.attempt_context` 非空时，表示这是一个多轮 objective run 的 **第 2 轮 attempt**。

### 核心规则

**1. attempt_context 是当前轮的执行调整指令，优先级高于 discovery_intent lanes**

```json
{
  "attempt_number": 2,
  "max_attempts": 2,
  "target_new_jobs": 10,
  "remaining_target": 6,
  "seen_companies": ["JPMorgan", "Goldman Sachs", "BlackRock"],
  "seen_urls": ["https://...", "https://..."],
  "previous_failure_summary": "High duplicate rate: 8/10 candidates already in catalog.",
  "pivot_hint": "Avoid the 3 seen companies. Switch to direct ATS boards (Greenhouse/Lever/Ashby) targeting mid-size asset managers and insurance firms not yet covered."
}
```

**2. `seen_companies` 和 `seen_urls` 是禁区**

- 不把 `seen_urls` 里的 URL 加入 candidate pool（即使搜索结果里出现了）
- 不把 `seen_companies` 作为主要搜索目标（除非 `pivot_hint` 明确指示要重新覆盖某家公司）

**3. `pivot_hint` 是策略调整指令，必须执行**

`pivot_hint` 是 Follow-up Planner 根据第 1 轮失败原因生成的具体调整方案。你必须将其作为本轮策略的核心指令。

**4. `remaining_target` 是本轮的目标**

本轮只需要找到 `remaining_target` 个数据库中没有的新岗位。不要继续收集已被上一轮覆盖过的公司的岗位（除非 pivot_hint 指示）。

**5. attempt_context 不存在时，按正常 discovery_intent 逻辑执行**

`attempt_context` 缺失或为空时，这是第 1 轮 attempt，完全按照 `discovery_intent` + `strategy_context` 正常执行。

### discovery_intent 字段速查

| 字段 | 你应该怎么用 |
|---|---|
| `intent_kind` | 了解这轮 run 的目标性质（directed / exploration / gap_fill） |
| `global_constraints.hard_constraints` | 强制约束，所有 lane 都适用 |
| `global_constraints.soft_preferences` | 优先考虑，可在 low-yield 时放宽 |
| `global_constraints.negative_preferences` | 降权方向，非绝对排除 |
| `search_lanes[].lane_id` | 用于 candidate 标注和 coverage_report 中的 lane 状态 |
| `search_lanes[].query_seeds` | 起始 query，可扩展但不能改变 lane 语义 |
| `search_lanes[].budget_share` | 按比例分配 max_queries |
| `search_lanes[].exclude_role_keywords` | 扩展 query 时避开这些词 |
| `search_lanes[].risk_of_false_positive` | 了解这个 lane 最容易走偏的方向 |
| `source_strategy.prefer_sources` | 优先用于 board_sync / site: 搜索 |
| `source_strategy.avoid_sources` | 跳过，与 strategy_context.avoid_sources 作用相同 |

---

## 硬性「不做」（I/O 层）

- 不 `career_search_session start` / `end`。
- 不写 `db/jobs.jsonl`、不写 final job report、不写 strategy_state.json。
- 不跑 processing pipeline。
- 不生成 Job Intelligence Report / Candidate Fit Report。
