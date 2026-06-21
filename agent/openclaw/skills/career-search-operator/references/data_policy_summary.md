# Data Policy — Discovery Run Summary

> 全局完整版见 `protocols/DATA_POLICY.md`。此处是 discovery run 的精炼边界。

## 允许的 source（公开，不登录）

- 公开公司 career page（直接 URL，无需登录）
- LinkedIn 公开搜索结果（不登录、不用 LinkedIn API）
- Indeed / Glassdoor 公开页面
- Google / Bing 搜索结果（仅作 discovery surface，搜索结果页本身不能成为候选 URL）

## 禁止

- 不登录任何平台、不绕过 paywall、不用 headless browser 模拟登录
- 不保存 PII（候选人信息、内部员工信息）
- discovery 阶段**不直接写数据库**（候选只通过 `career_log_candidates` 写入 `candidate_pool.jsonl`；岗位入库由 worker Validator Gate 通过后执行）
- 不调用不在 exec allowlist 的任何 wrapper（`career_sync_board`、`career_classify_source`、`career_register_board`、`career_search_session` 等均不在 MVP allowlist）

## Budget

单次 run 的 budget 来自 `payload.budget`（`AgentBudget`）：

| 字段 | 含义 | 默认值 |
|---|---|---|
| `max_tool_calls` | 总 tool call 次数上限（含 web_search / web_fetch / exec） | 30 |
| `max_candidates` | 最多 log 候选数 | 50 |
| `max_new_sources` | 最多新增来源数 | 10 |
| `timeout_seconds` | 墙钟时间上限（平台强制终止） | 900 |

用 `career_search_status --task-spec <input.json 路径>` 定期确认用量。

## 最易错的两条规则

1. **搜索结果页是 discovery surface，不是 candidate URL。** 从搜索结果里提取具体 job posting URL → `web_fetch` 或 `career_fetch_source` 确认 → 才能 `career_log_candidates`。
2. **`career_fetch_source` 和 `web_fetch` 互补，不互斥。** `career_fetch_source` 适合已知是 ATS URL（greenhouse / lever / ashby / workday）的情况，做 fetch + normalize；`web_fetch` 适合 HTML 公司 career page 或需要读取 listing 内容的场景。两者都可以作为 evidence，都需要确认真实 JD 内容后才 log candidate。
