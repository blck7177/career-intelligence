# Discovery Moves

这些 moves 可以**自由组合、不限顺序**。根据 `payload.discovery_intent` 和当前 discovery 状态选择最有效的 move。

**MVP allowlist 工具（全部通过 `--task-spec <json> --output <json>` 调用）：**

```
web_search          OpenClaw native — 发现 job posting URL / ATS URL
web_fetch           OpenClaw native — 读取 job detail page / career listing page
career_fetch_source wrapper — fetch + normalize 一个具体 ATS/job URL
career_log_candidates wrapper — 把确认的候选写入 candidate_pool.jsonl
career_search_status  wrapper — 查当前 budget / candidate_count 状态
career_write_manifest wrapper — 写最终 output_manifest.json（只调一次）
```

**禁止：** `career_sync_board`、`career_classify_source`、`career_register_board`、`career_search_session`、bash/sh/python -c/curl/wget。这些不在 exec allowlist，调用会立即失败。

---

## 目录

- [Move 1: Direct Web Search](#move-1-direct-web-search)
- [Move 2: Targeted ATS Search](#move-2-targeted-ats-search)
- [Move 3: Career Page Snowball](#move-3-career-page-snowball)
- [Move 4: Source Pivot](#move-4-source-pivot)
- [Move 选择指南](#move-选择指南)

---

## Move 1: Direct Web Search

适合：探索新公司、新方向，在搜索结果里发现具体 JD URL。

```
web_search("<role keywords> <location> jobs")
  → 从搜索结果中提取具体 job posting URL（不是搜索结果页本身）
  → web_fetch 每个候选 URL，确认是真实 JD 内容
  → career_log_candidates
```

**强制顺序：每条候选必须有 web_fetch 确认，再 career_log_candidates。**

`career_log_candidates` task-spec 示例：

```json
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

调用方式：

```
tool: exec
name: career_log_candidates
args:
  --task-spec /tmp/log_candidates_spec.json
  --output /tmp/log_candidates_result.json
```

返回：`logged_count`、`logged_urls`、`errors`

---

## Move 2: Targeted ATS Search

适合：已知某 ATS 平台（Greenhouse / Lever / Ashby）上有相关岗位，精准 site: 搜索。

```
web_search("site:boards.greenhouse.io <role keywords> <location>")
  OR
web_search("site:jobs.lever.co <role keywords>")
  OR
web_search("site:jobs.ashbyhq.com <role keywords>")
  → 提取具体 job posting URL（形如 greenhouse.io/<company>/jobs/<id>）
  → career_fetch_source（fetch + normalize ATS job page）
  → career_log_candidates
```

`career_fetch_source` task-spec 示例：

```json
{
  "url": "https://boards.greenhouse.io/acme/jobs/12345",
  "source_type": "greenhouse",
  "run_id": "<来自 input.json>",
  "task_id": "<来自 input.json>",
  "artifacts_dir": "/app/data/agent_artifacts"
}
```

调用方式：

```
tool: exec
name: career_fetch_source
args:
  --task-spec /tmp/fetch_source_spec.json
  --output /tmp/fetch_source_result.json
```

返回：`url`、`text`（最多 50k chars）、`final_url`、`content_length`

用 `text` 内容确认是真实 JD 后，再调 `career_log_candidates`。

---

## Move 3: Career Page Snowball

适合：公司使用自建 HTML career page（非 Greenhouse/Lever/Ashby），或需要深入某公司岗位列表。

```
web_fetch("<company>/careers or <company>/jobs listing page")
  → 从 listing 页面内容里提取具体岗位 detail URL
  → 对每个 detail URL: web_fetch 确认真实 JD 内容
  → career_log_candidates
```

关键规则：
- listing page 本身不能成为候选 URL
- 每条候选 URL 必须是具体职位的 detail page
- `web_fetch` 到 403/blocked → 跳过该公司，在 coverage_report 里标注

---

## Move 4: Source Pivot

适合：当前 source / query 方向持续无结果或被封锁时，主动切换。

**触发条件：**
- `web_fetch` 返回 403 / 需要登录 / 无相关内容
- 多次 `web_search` 只返回聚合器页面（LinkedIn jobs/search、Indeed search、Google jobs）
- `career_fetch_source` 连续失败

**pivot 动作：**
- LinkedIn / Indeed 登录墙 → 改用 `site:boards.greenhouse.io` 或 `site:jobs.lever.co` targeted search
- Workday blocked → 改用公司官网 career page 搜索（Move 3）
- 大平台搜索结果太宽 → 加 `site:` 前缀精准 ATS 搜索（Move 2）
- 某 role keyword 无结果 → 尝试 `discovery_intent.target_role_families` 里其他 family 的别名和同义词

**记录规则：** 每次 pivot 原因必须在 `coverage_report.md` 里注明，格式：

```markdown
- <source/direction>: exhausted (<N> queries, <N> candidates) — reason: <failure mode>
```

---

## Move 选择指南

| 场景 | 优先 Move |
|---|---|
| 探索新公司 / 新方向 | Direct Web Search (Move 1) |
| 已知是 Greenhouse / Lever / Ashby ATS | Targeted ATS Search (Move 2) |
| 公司有自建 career page | Career Page Snowball (Move 3) |
| 当前 source 被封 / 无结果 | Source Pivot (Move 4) |
| budget 快用完 | 专注最高 yield 的已知方向，不再开新 source |

---

## Budget 追踪

每 5 次 discovery action 后用 `career_search_status` 确认 budget：

```
tool: exec
name: career_search_status
args:
  --task-spec /app/data/agent_artifacts/<run_id>/<task_id>/input.json
  --output /tmp/status_result.json
```

返回：`candidates_logged`、`tool_calls_used`、`budget_remaining.candidates`、`budget_remaining.tool_calls`

达到 `payload.budget.max_candidates` 或 `payload.budget.max_tool_calls` → 停止 discovery loop，进入收尾流程（写 coverage_report → career_write_manifest）。
