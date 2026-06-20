# Source Verification Gate（反捏造）

一个不联网的 research agent 也能凭训练知识编出像模像样的 `research_notes.md`——这正是必须防的失败模式（对标 search 侧 `queries_run==0` 闸门）。平台会校验，你无法伪造。

## 两层证据

- **Layer A（主，强）**：gateway 从 agent run log 解析真实发生的 `web_fetch` 调用。你不调用就不存在这条记录——无法伪造。
- **Layer B（辅，弱）**：你通过 `career_research_session log-fetch` 写的 fetch ledger，仅在 run log 不暴露 tool calls 时兜底。冲突时 Layer A 胜。

## 每次 web_fetch 后立即记 ledger（强制）

```bash
./wrappers/career_research_session log-fetch \
  --job-id <job_id> --inputs-hash <research_inputs_hash> --url <fetched_url>
```

## research_sources.json 结构（供逐源核对）

写到 spec 的 `expected_output_paths.research_sources` 路径：

```json
[
  {
    "url": "https://...",
    "title": "...",
    "source_type": "company_website|press_release|job_board|news|linkedin|other",
    "related_jd_signal": "...",
    "boundary": "..."
  }
]
```

- 每条 `url` 必须是你**真实 `web_fetch` 过**的 URL（校验器用 `url_hash` 与真实 fetch 集合逐一核对）。
- `related_jd_signal` 与 `boundary` 必须**非空**，否则该源降级为 unverified。

## 判定逻辑（你需要知道结果如何被裁定）

- 零真实 fetch → **failed**。
- notes 非空但 sources 空 → **failed**。
- 逐源 `url_hash` 核对：全对不上 → **failed**；部分命中 → **partial**；全部命中 → **passed**。
- `passed` / `partial` 才会被喂进报告；`failed` → worker 降级为 JD-only。

结论：**先 `web_search` → `web_fetch` 真实确认 → `log-fetch` → 再把该 URL 写进 sources。** 工具调用同样遵守「写文件用 write tool，exec 只用于 `./wrappers/*`，不用内联脚本」。
