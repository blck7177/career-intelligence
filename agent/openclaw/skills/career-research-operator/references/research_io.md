# Research — I/O Contract (bounded)

> 全局契约见 `protocols/AGENT_IO_CONTRACT.md`。此处只保留 bounded research turn 需要的部分。

```
Worker owns workflow.  Agent owns the bounded research action.  Service owns persistence + report.
```

## 输入：读 task spec 文件（不要靠记忆）

平台在你的 prompt 里给一个 task spec 文件路径。用 read tool 读它，字段：

```json
{
  "job_id": "job_xxxxxxxx",
  "research_inputs_hash": "....",
  "company": "...", "title": "...", "source_url": "...",
  "jd_excerpt": "...",
  "queries": [{"query": "...", "priority": "high|medium|low", "purpose": "..."}],
  "context_gaps": ["..."],
  "avoid_queries": ["..."],
  "max_fetches": 3,
  "expected_output_paths": {
    "research_notes": ".../research_notes.md",
    "research_sources": ".../research_sources.json",
    "fetch_ledger": ".../research_fetch_ledger.jsonl"
  }
}
```

## 平台在你之前已经做完的事

- 已解析 `job_record` + JD，算好 `research_inputs_hash`（缓存/新鲜度 key）。
- `research_planner` 已**派生好 `queries` / `context_gaps` / `avoid_queries`**——query 不是你自由发挥，按给定优先级 high → medium → low 执行，跳过 `avoid_queries`。

## 你只做这一件事

围绕**一个已知 job/company/team** 做 bounded 补充研究：`web_search` → `web_fetch`（每公司最多 `max_fetches` 次）→ 写 `research_notes.md` + `research_sources.json`，并对每次 fetch 记 ledger（见 `source_verification_gate.md`）。

研究目标是澄清 JD：公司业务背景、team/division context、role 在组织中的位置、product/business line、为什么这个岗位存在。**不是找新岗位。**

## 平台在你之后会做的事（你不要碰）

1. **`research_validator`**：反捏造校验（逐源用 `url_hash` 核对真实 fetch 集合）。
2. **`analysis_service.create_job_report`**：把你的 notes 作为 `[RESEARCH]` 上下文喂给 LLM 生成 Job Intelligence Report。
3. 校验 **failed → 降级为 JD-only report**（不崩，非致命）。所以 bundle 不可用不会让任务失败，但你的研究就白做了。

## 完成标志（expected_outputs）

`research_notes.md` 与 `research_sources.json` 都已写到 spec 指定路径，且每条 source 都有对应的真实 `web_fetch` + `career_research_session log-fetch` 记录。

## 硬性「不做」

- 不生成 Job Intelligence Report、不调 role analysis。
- 不写 MetadataStore、不写 `db/jobs`。
- 不做候选人 fit、不写简历 / cover letter。
- 不写未经 `web_fetch` 确认的来源。
