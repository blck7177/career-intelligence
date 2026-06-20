# Data Policy — Discovery Run Summary

> 全局完整版见 `protocols/DATA_POLICY.md`。此处是 discovery run 的精炼边界。

## 允许的 source（公开，不登录）

- 公开公司 career page（直接 URL）
- 已注册的 ATS boards（Greenhouse / Lever / Ashby）通过 connector 同步
- LinkedIn 公开搜索结果（不登录、不用 LinkedIn API）
- Indeed / Glassdoor 公开页面
- Google / Bing 搜索结果（仅作 discovery surface，搜索结果页本身不能成为候选）
- `configs/source_policy.yaml` 中启用的第三方 job search API

## 禁止

- 不登录任何平台、不绕过 paywall、不用 headless browser 模拟登录
- 不保存 PII（候选人信息、内部员工信息）
- discovery 阶段**不直接写 `db/jobs.jsonl`**（候选只经 `career_log_candidates` 或 board sync；岗位入库由 worker pipeline 完成）
- 不直接写 `configs/company_boards.yaml`（必须通过 `career_register_board` wrapper）

## Budget

- 单次 session 上限取 spec 的 `budget` 字段：
  - `max_queries`（web_search 次数，默认 30）
  - `max_pages`（web_fetch 次数，默认 40）
  - `max_board_syncs`（board_sync 次数，默认 10）
- web_fetch 之间建议间隔约 1 秒

## 最易错的两条规则

1. **搜索结果页是 discovery surface，不是 candidate URL。** 从搜索结果里提取具体 job posting URL → `web_fetch` 确认 → 才能 `career_log_candidates`。
2. **Board sync 不替代 web search。** Board sync 用于已知 active 公司的批量收集；web search 用于发现 `company_boards.yaml` 里没有的新公司和新来源。两者互补，不互斥。
