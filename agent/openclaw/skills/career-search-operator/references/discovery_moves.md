# Discovery Moves

这些 moves 可以**自由组合、不限顺序**。根据 task spec 的 `catalog_context` 和当前 discovery 状态选择最有效的 move。

## 目录
- [Move 1: Board Sync](#move-1-board-sync)
- [Move 2: Web Search](#move-2-web-search)
- [Move 3: Source Classification & Board Registration](#move-3-source-classification--board-registration)
- [Move 4: Targeted Site Search](#move-4-targeted-site-search)
- [Move 5: Career Page Snowball](#move-5-career-page-snowball)
- [Move 6: Query Expansion](#move-6-query-expansion)
- [Move 7: Source Pivot](#move-7-source-pivot)
- [Move 选择指南](#move-选择指南)

---

## Move 1: Board Sync（优先用于已知 ATS 公司）

对 `configs/company_boards.yaml` 中 `status: active` 的公司，优先 board sync 而不是 web search。Board sync 比 HTML fetch 稳定，无 bot 保护问题，一次获取全部 published jobs。

**调用前必须推断过滤参数（不能裸调）：**

```bash
# 1. 先 dry-run 检查预期命中数
./wrappers/career_sync_board \
  --source <ats_type> --slug <company_slug> \
  --session-id <session_id> --workspace-id <workspace_id> \
  --location-filter "<locations from profile>" \
  --title-keywords "<keywords from profile>" \
  --dry-run

# 2. 满意后去掉 --dry-run 正式执行
./wrappers/career_sync_board \
  --source <ats_type> --slug <company_slug> \
  --session-id <session_id> --workspace-id <workspace_id> \
  --location-filter "<loc_1>,<loc_2>" \
  --title-keywords "<keyword_1>,<keyword_2>,<keyword_3>"
```

- `would_keep = 0`：放宽 `--title-keywords`，或去掉 `--location-filter` 先看分布
- `would_keep > 30`：收紧条件，或分批处理

Board sync 候选自动写入 `candidate_pool.jsonl`，不需要额外调 `career_log_candidates`。

---

## Move 2: Web Search（适合发现新公司 / 新来源）

`web_search` tool → 从结果中提取具体 JD URL → 对每个候选 URL 单独 `web_fetch` 确认 → `career_log_candidates`。

```
web_search("site:greenhouse.io <role_keywords> <location>")
  → 提取 job detail URLs（不是搜索结果页本身）
  → web_fetch 每个 URL 确认真实 JD 内容
  → career_log_candidates
  → career_search_session log-query（每次 web_search 必做）
```

**强制日志顺序（web search path）：**
```
web_search → career_search_session log-query → web_fetch → career_log_candidates
```

`log-query` 记录格式（inline 形式）：
```bash
./wrappers/career_search_session log-query \
  --session-id <id> --workspace-id <id> \
  --query-text "<actual query you searched>" \
  --source-type <company_career_page|ats_board|aggregator|unknown> \
  --valid-url-count <int> --candidate-yield <int> --failure-mode <none|blocked_403|no_results|other>
```

`career_log_candidates`（单条）：
```bash
./wrappers/career_log_candidates \
  --session-id <id> --workspace-id <id> \
  --url "<job posting url>" --title "<title>" --company "<company>" \
  --location "<loc>" --relevance relevant \
  --reason "<why it matches the profile>" --workstream-hint "<workstream>"
```

---

## Move 3: Source Classification & Board Registration（发现新 ATS 时）

在 web_search / web_fetch 中发现 `configs/company_boards.yaml` 里没有的公司的 ATS board URL 时：

```bash
# 1. 分类 ATS 类型
./wrappers/career_classify_source --url <url>

# 2. 验证可访问性（Greenhouse: boards-api.greenhouse.io; Lever: api.lever.co）
# 3. 注册
./wrappers/career_register_board \
  --slug <company_snake_case> \
  --source <greenhouse|lever|ashby|workday|html> \
  --board-token <token_from_url> \
  --status <active|best_effort|hard_source> \
  --verified-at <today_date> \
  --notes "<说明：发现于搜索结果，已验证 API 可访问>"
```

注册后在同一 session 内即可用 `career_sync_board` 同步该公司（Move 1）。

**注册时机：**
- 发现新 greenhouse.io / lever.co / ashby.com URL → 立即注册
- 发现某公司 career page 返回 403/blocked → 注册为 `status: hard_source`
- 发现某公司用 Workday 但 detail page 可访问 → 注册为 `status: best_effort`

---

## Move 4: Targeted Site Search

对特定公司的 career page 做精准搜索：

```
web_search("site:careers.<company>.com <role_keywords> <location>")
```

适用于：不在 boards 里的公司，或 board sync 结果为空时的补充。

---

## Move 5: Career Page Snowball

`web_fetch` 公司 career page listing → 从页面上提取相关岗位 URL → `web_fetch` 每个 detail URL → `career_log_candidates`。

适用于：HTML-based 公司（非 Greenhouse/Lever/Ashby），或需要深入某公司内部岗位结构的场景。

---

## Move 6: Query Expansion

从 JD 内容里发现新术语 → 生成新 query：
- 从 `web_fetch` 到的 JD 内容里提取 title 变体、技术词汇
- 将这些术语用于下一组 web_search queries

例：fetch 到 `"<role abbreviation>"` JD 后 → 新 query `"<full role title> <location>"`

---

## Move 7: Source Pivot

当一个 source 方向持续无结果时，切换：
- Workday blocked → 改用 LinkedIn 公开搜索 + 公司官网 career page
- LinkedIn 登录墙 → 改用 Indeed 公开页面
- 大平台结果不精准 → 改用 `site:<specific_ats>` targeted search

---

## Move 选择指南

| 场景 | 优先 Move |
|---|---|
| 已知 active ATS 公司 | Board Sync (Move 1) |
| 发现新公司 ATS URL | Classify + Register (Move 3) → Board Sync |
| 寻找新公司/新来源 | Web Search (Move 2) |
| 某公司结果为空 | Targeted Site Search (Move 4) |
| 发现新 JD 术语 | Query Expansion (Move 6) |
| 当前 source blocked | Source Pivot (Move 7) |
