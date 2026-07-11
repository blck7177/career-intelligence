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

围绕**一个已知 job/company/team** 做 bounded 补充研究：`web_search` → `web_fetch`（每公司最多 `max_fetches` 次）→ 写 `research_notes.md` + `research_sources.json`（gateway 自动观测所有 tool calls，见 `source_verification_gate.md`）。

研究目标是澄清 JD：公司业务背景、team/division context、role 在组织中的位置、product/business line、为什么这个岗位存在。**不是找新岗位。**

## source_url 抓不到正文时：可以用第三方镜像，但有严格条件

`source_url` 常见抓不到正文（JS 渲染的 ATS 页面、登录墙）。这种情况下，你可以 `web_search` 该岗位标题 + 公司名，看是否有第三方职位聚合站（BuiltInNYC、ZipRecruiter、digitalhire 等）转发了同一条岗位，`web_fetch` 确认后把转发正文当作 `jd_text` 使用——但必须同时满足：

1. **标题、公司都对得上**，且转发内容读起来明显是同一条岗位的正文（不是相似岗位、不是过期岗位的缓存快照）。
2. **只要有任何理由怀疑这不是同一条具体岗位**（例如公司同时挂着多个标题相同但明显是不同批次/不同 req 的岗位，你在 `source_url` 或搜索结果里能看到这种迹象），**宁可 `jd_text` 留空**，不要猜。你不需要、也没有能力核对 req 编号是否一致——不确定就不用。
3. 在 `output_manifest.json` 里把 `jd_source_type` 设为 `"mirror"`（默认是 `"original"`，即 `jd_text` 确实来自 `source_url` 本身时才用默认值）。
4. 在 `research_notes.md` 对应 source 的 `Boundary` 里注明"转发/镜像来源，非雇主原始页面"。

这条规则不改变 evidence 铁律：镜像来源的 `jd_text` 一样必须是你真实 `web_fetch` 过的内容，一样受 `source_verification_gate.md` 的反捏造校验约束。

## 平台在你之后会做的事（你不要碰）

1. **`research_validator`**：反捏造校验（逐源用 `url_hash` 核对真实 fetch 集合）。
2. **`analysis_service.create_job_report`**：把你的 notes 作为 `[RESEARCH]` 上下文喂给 LLM 生成 Job Intelligence Report。
3. 校验 **failed → 降级为 JD-only report**（不崩，非致命）。所以 bundle 不可用不会让任务失败，但你的研究就白做了。

## output_manifest.json 必填字段

除 platform 要求的通用字段（`invocation_id`, `status`, `stop_reason`, `artifact_paths`, `summary`）外，还必须包含：

```json
{
  "job_id": "<job_id from input spec>",
  "citations_count": 2,
  "jd_text": "<完整 JD 正文；从 source_url fetch 后提取，或按上面的镜像规则从第三方转发提取；都拿不到则为 null>",
  "jd_source_type": "original | mirror"
}
```

Worker 会读取 `jd_text` 写入数据库。`jd_source_type="original"` 会直接促进 job 进入 `reportable` 状态；`jd_source_type="mirror"` 只有在该 company+title 组合在平台里唯一时才会被自动 promote，否则 job 留在 `discovered` 供人工确认（原因见上面第 2 条）。`jd_text` 为 `null` 不会导致任务失败，但会让 job report 降级为 JD-only fallback。

## 完成标志（expected_outputs）

`research_notes.md`、`research_sources.json` 和 `output_manifest.json`（含 `jd_text`）都已写到 spec 指定路径，且每条 source 都有对应的真实 `web_fetch` 记录（gateway 自动观测）。

## 硬性「不做」

- 不生成 Job Intelligence Report、不调 role analysis。
- 不写 MetadataStore、不写 `db/jobs`。
- 不做候选人 fit、不写简历 / cover letter。
- 不写未经 `web_fetch` 确认的来源。
