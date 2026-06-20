# Data Policy — Research Summary

> 全局完整版见 `protocols/DATA_POLICY.md`。此处是 bounded research turn 的精炼边界。

## 允许的 source（公开，不登录）

- 公开公司 career page / 公司官网。
- 公司 newsroom / press release。
- 公开新闻、行业报道。
- LinkedIn 公开页面（不登录、不用 API）。
- Google / Bing 搜索结果（仅作 discovery surface，不作为来源本身）。

## 禁止

- 不登录、不绕过 paywall、不用 headless browser 模拟登录。
- 不保存 PII（具体员工姓名 / 联系方式 / 内部信息）。
- 不写 `db/jobs`、不写 MetadataStore（持久化归平台）。
- 跳过 `avoid_queries`、google / LinkedIn 搜索结果页、aggregator 垃圾页。

## Budget & 证据

- **每个公司最多 `max_fetches` 次 `web_fetch`**（spec 给定，默认 3）。宁可少而精。
- 每条来源必须保留真实 URL（evidence preservation），且必须是你 `web_fetch` 过的（见 `source_verification_gate.md`）。
- 只写 fetch 确认的内容，不写推测。
