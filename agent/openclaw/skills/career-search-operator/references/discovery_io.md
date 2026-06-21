# Discovery Run — I/O Contract

```
Worker owns lifecycle, intent translation, persistence, and validator gate.
Agent owns discovery strategy inside the run budget.
Service owns canonical database.
```

## 输入：读 input.json

平台把 task spec 路径写进你的 prompt。用 read tool 读它：

```
/app/data/agent_artifacts/<run_id>/<task_id>/input.json
```

### 顶层结构

```json
{
  "invocation_id": "<uuid>",
  "run_id": "<uuid>",
  "task_id": "<uuid>",
  "workspace_id": "<workspace_id>",
  "task_type": "agent.job_discovery",
  "skill_contract_version": "career-search-operator@1",
  "output_manifest_path": "/app/data/agent_artifacts/<run_id>/<task_id>/output_manifest.json",
  "budget": {
    "max_tool_calls": 30,
    "max_candidates": 50,
    "max_new_sources": 10,
    "timeout_seconds": 900
  },
  "payload": {
    "discovery_intent": { ... },
    "catalog_context": null,
    "source_registry_snapshot": null,
    "previous_run_diagnostics": null,
    "budget": { ... },
    "output_paths": { ... }
  }
}
```

**你需要的字段全部在 `payload` 里。** 顶层的 `budget` 和 `output_manifest_path` 是平台用的，agent 应优先读 `payload.budget` 和 `payload.output_paths`。

---

### `payload.discovery_intent` — 你要找什么

这是 Intent Translator 的输出，是你的核心指令。

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `interpreted_goal` | 一句话目标 | **第一步读这个**，理解本轮 run 的目的 |
| `raw_user_request` | 用户原始请求（保留原文） | 审计用，理解用户真实意图 |
| `search_mode` | `direct` / `exploratory` / `profile_guided` | 决定你的扩展策略，见下方规则 |
| `target_role_families` | 要搜索的 role 方向列表 | 每条含 `name`, `rationale`, `source`, `confidence` |
| `excluded_role_families` | 明确排除的 role 方向 | 搜索中完全不触碰这些方向 |
| `hard_constraints` | 强制约束 | **必须遵守**，见下方约束规则 |
| `soft_preferences` | 优先偏好 | 可在排序和过滤时参考，低 yield 时可放宽 |
| `expansion_scope` | `narrow` / `standard` / `wide` | 控制你可以扩展多远，见下方规则 |
| `profile_role` | `none` / `supporting` / `primary` | 了解 profile 在这轮的权重 |
| `capability_signals` | Profile 能力聚类（无 profile 时为空） | 作为扩展搜索的参考信号 |
| `ambiguity_flags` | 未解决的歧义 | 信息性，不是指令；遇到歧义时在 coverage_report 中注明 |

**`expansion_scope` 规则：**

- `narrow`（direct mode）：只搜 `target_role_families` 里列出的方向。同义词和 title alias 允许（如 "IPV" = "independent price verification"），不扩展到未列出的相邻方向。
- `standard`（exploratory / profile_guided）：可以在 intent 精神范围内适度扩展到语义相邻方向。
- `wide`：可以广泛探索，但必须锚定在 intent 的核心方向上。

**`hard_constraints` 规则（强制）：**

- `location` 非空 → 只 log 匹配该地点的岗位
- `seniority` 非空 → 只 log 匹配该级别的岗位
- `exclude_role_types` 非空 → query 中不包含这些方向，发现后不 log
- `must_include_keywords` 非空 → 候选必须包含这些词
- `work_arrangement` 非空 → 仅 log 匹配工作方式的岗位
- 某字段为 null 或空 → 无该约束，不要自行推断

---

### `payload.catalog_context` — 去重

MVP 阶段此字段为 `null`。非 null 时：

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `recently_seen_urls` | 已在 catalog 里的 job URL | **绝不重复 log 这些 URL** |
| `recently_seen_companies` | 已覆盖充分的公司 | 降低这些公司的优先级，优先探索新来源 |
| `existing_job_count` | 当前 catalog 里的岗位数量 | 了解已有规模，调整目标设定 |

---

### `payload.source_registry_snapshot` — 来源指导

MVP 阶段此字段为 `null`。非 null 时：

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `known_boards` | 已知活跃的 ATS 来源 | 优先用 `career_fetch_source` 直接访问 |
| `avoid_sources` | 已知失败的来源（含原因） | 跳过，不浪费 budget |
| `effective_query_patterns` | 历史产出过真实 JD URL 的 query 模式 | 作为 `web_search` 的起点参考 |

---

### `payload.previous_run_diagnostics` — 历史经验

MVP 阶段此字段为 `null`。非 null 时：

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `coverage_gaps` | 上轮没覆盖到的方向 | 优先把 budget 倾向这些方向 |
| `key_learnings` | 历史 run 的关键发现 | 理解这个搜索空间已知的坑和规律 |
| `recommended_next_searches` | 上轮建议的下一步方向 | 作为本轮起始策略参考，你可以调整 |

---

### `payload.budget` — 执行预算

| 字段 | 含义 | 你应该怎么用 |
|---|---|---|
| `max_tool_calls` | 总 tool call 上限 | 用 `career_search_status` 追踪用量 |
| `max_candidates` | 最多 log 候选数 | 达到上限后停止搜索 |
| `max_new_sources` | 最多新增来源数 | 控制 source discovery 的规模 |
| `timeout_seconds` | 墙钟时间上限 | 平台在超时后会强制终止 |

用 `career_search_status` 定期确认当前消耗：

```
tool: exec
command: python tools/wrappers/agent_tools/career_search_status.py \
  --task-spec /app/data/agent_artifacts/<run_id>/<task_id>/input.json \
  --output /tmp/status.json
```

返回：`candidates_logged`、`tool_calls_used`、`budget_remaining.candidates`、`budget_remaining.tool_calls`

---

### `payload.output_paths` — 你要写到哪里

| 字段 | 文件 | 由谁写 |
|---|---|---|
| `candidate_pool_path` | `candidate_pool.jsonl` | `career_log_candidates` wrapper 自动写入 |
| `search_ledger_path` | `search_ledger.jsonl` | 你手动写（可选，记录每次搜索行动） |
| `trace_events_path` | `trace_events.jsonl` | wrapper 自动追加（`career_log_candidates`、`career_fetch_source` 每次调用后各写一行） |
| `coverage_report_path` | `coverage_report.md` | **你手动写（必须）** |
| `output_manifest_path` | `output_manifest.json` | `career_write_manifest` wrapper 写入 |

---

## 平台在你之前已做完的事

- 解析用户 `input_snapshot` → `JobDiscoveryFrontendInput`
- 调用 `IntentTranslator` → 产出 `DiscoveryIntent`（LLM 1次调用，temperature=0.1）
- 构建 `DiscoveryTaskSpec` → 写入 `input.json`
- 创建 `agent_invocation` 记录
- 发出 `task_event(intent_translated)` — UI 可见
- **Session 已存在**，你只需确认 budget，**绝不** `career_search_session start`

---

## 你负责产出的内容

**必须产出（平台 validator 会检查）：**

1. `coverage_report.md` — 写到 `payload.output_paths.coverage_report_path`
2. `output_manifest.json` — 调用 `career_write_manifest` 写到 `payload.output_paths.output_manifest_path`

Manifest 必须包含：

```json
{
  "invocation_id": "<来自 input.json 顶层>",
  "status": "completed | partial | failed",
  "stop_reason": "<为什么停止>",
  "artifact_paths": {
    "candidate_pool": "<payload.output_paths.candidate_pool_path>",
    "search_ledger": "<payload.output_paths.search_ledger_path>",
    "trace_events": "<payload.output_paths.trace_events_path>",
    "coverage_report": "<payload.output_paths.coverage_report_path>"
  },
  "summary": {
    "candidate_count": <int>,
    "sources_tried": [...],
    "sources_added": [...]
  }
}
```

**注意**：`career_write_manifest` wrapper 会自动把 `summary` 里的 `candidate_count`、`sources_tried`、`sources_added` 提升到 manifest 顶层（Validator Gate 从顶层字段读取）。你只需在 `summary` 里填写即可，无需额外操作。

```json
```

**可选：**

- `search_ledger.jsonl` — 增量追加，每次搜索行动记一条（`web_search` query、`career_fetch_source` URL 等）

---

## Tool 调用方式

所有 wrapper 都是 `--task-spec <临时json> --output <结果json>` 模式。

### `career_log_candidates`

```json
// task-spec 内容：
{
  "run_id": "<来自 input.json>",
  "task_id": "<来自 input.json>",
  "artifacts_dir": "/app/data/agent_artifacts",
  "candidates": [
    {
      "url": "https://boards.greenhouse.io/acme/jobs/12345",
      "title": "Market Risk Analyst",
      "company": "Acme Bank",
      "source_type": "greenhouse",
      "notes": "Associate level, NYC, valuation control team"
    }
  ]
}
```

返回：`logged_count`、`logged_urls`、`errors`

### `career_fetch_source`

```json
// task-spec 内容：
{
  "url": "https://boards.greenhouse.io/acme/jobs/12345",
  "source_type": "greenhouse",
  "run_id": "<来自 input.json>",
  "task_id": "<来自 input.json>",
  "artifacts_dir": "/app/data/agent_artifacts"
}
```

返回：`url`、`text`（最多 50k chars）、`final_url`、`content_length`

### `career_write_manifest`

```json
// task-spec 内容：
{
  "invocation_id": "<来自 input.json 顶层>",
  "status": "completed",
  "stop_reason": "budget.max_candidates reached",
  "artifact_paths": {
    "candidate_pool": "<payload.output_paths.candidate_pool_path>",
    "search_ledger": "<payload.output_paths.search_ledger_path>",
    "trace_events": "<payload.output_paths.trace_events_path>",
    "coverage_report": "<payload.output_paths.coverage_report_path>"
  },
  "summary": {
    "candidate_count": 28,
    "sources_tried": ["greenhouse.io/acme", "lever.co/xyz"],
    "sources_added": ["ashby.io/newco"]
  }
}
// output 路径：payload.output_paths.output_manifest_path
```

wrapper 会自动将 `summary.candidate_count`、`summary.sources_tried`、`summary.sources_added` 提升到 manifest 顶层，供 Validator Gate 读取。

---

## 平台在你之后会做的事（你不要碰）

1. **Validator Gate**：检查 manifest schema、artifact 存在性、budget 合规、以及 trace_events 里是否有真实 discovery action（`web_search` / `web_fetch` / `career_fetch_source`）。无真实 action 但 candidate_count > 0 → 直接 `needs_review`。
2. **Artifact 入库**：validator 通过后，把 `artifact_paths` 里的路径写入 `artifacts` 表。
3. **Run status 更新**：task → `succeeded` 或 `needs_review`，UI 可见。
4. **Candidate ingest**（未来）：`candidate_pool.jsonl` 里的候选经 dedup / normalize 后写入 `jobs` 表。

---

## 硬性「不做」（I/O 层）

- 不写 `jobs` 表，不写 `strategy_state`，不生成 job report / fit report
- 不调用 `career_search_session start` / `end`（session 生命周期归平台）
- 不自行修改 `input.json`
- 不写 output manifest 之外的任意文件到 `<run_id>/<task_id>/` 以外的路径
- 不把 `catalog_context.recently_seen_urls` 里的 URL log 进 candidate pool
- 不绕过 `hard_constraints`——它们是平台级强制约束，不是建议
