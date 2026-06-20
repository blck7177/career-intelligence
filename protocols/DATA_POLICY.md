# Data Policy

## Source Allowlist
- 公开公司 career page（直接 URL，不需登录）
- LinkedIn 公开搜索结果（不登录，不使用 LinkedIn API）
- Indeed / Glassdoor 公开页面
- Google / Bing 搜索结果
- 第三方 job search API（如 SerpAPI，需在 source_policy.yaml 中启用）

## 禁止行为
- 不登录任何平台绕过 paywall
- 不使用 headless browser 模拟登录
- 不大规模批量抓取（每次 run 上限：50 条 job，每个 source 上限：20 条）
- 不保存包含 PII 的数据（候选人信息、内部员工信息）
- 不在 search 阶段直接写入 db/jobs.jsonl

## 存储规范
- raw JD 文本保存到 runs/<timestamp>/raw_jds/（内容不 commit 到 git）
- db/jobs.jsonl 只存结构化字段（不存完整 HTML 或 raw text）
- source_url 必须保留（evidence preservation）
- runs/<timestamp>/ 目录下的 search_ledger.jsonl / candidate_pool.jsonl 可以 commit

## 去重规则
- 去重 key：MD5(source_url)，存储为 url_hash
- 同一 URL 再次发现时：upsert（追加新记录，job_index 更新，保留原 job_id）
- title + company + location 相同但 URL 不同：保留两条，标记 possible_duplicate: true

## Rate Limiting
- web fetch 之间建议间隔 1 秒
- 单次 session 不超过 40 次 fetch
- LLM API 调用有 30s timeout，最多 3 次 retry
