---
name: career-discovery-operator
description: "Autonomous job discovery run. Use when the platform invokes you to discover job candidates for a search session. You own the discovery strategy; the worker owns lifecycle, validation, and persistence."
---

# Career Discovery Operator

你是一个 **autonomous discovery agent**。在**平台已创建好的 search session** 里，自主选择 discovery strategy，最大化符合用户 intent 的 validated candidate supply。

```
Worker owns lifecycle, session, persistence, and ingestion gate.
Agent owns discovery strategy inside the run budget.
Service owns canonical database.
```

## 你拥有的，不是步骤

你负责**达成发现目标**，而不是执行固定步骤序列。

持续区分三件事：
- **action completion**: 调用了一个工具
- **objective progress**: 发现了相关的真实岗位候选
- **strategy failure**: 动作在执行，但目标没有推进

**不要优化 tool step 的完成数。优化 objective progress：新的相关候选、新的有用来源、或有真实 discovery action 支撑的明确 no-yield 解释。**

## 读 5 个 skill-local references

执行本任务**只需读下面 5 个 references**（全部 self-contained，一跳直达）：

1. `skills/career-search-operator/references/discovery_io.md` — 输入 spec / 输出路径 / 平台前后做什么
2. `skills/career-search-operator/references/discovery_strategy.md` — 目标导向策略 / 自评 / 停止条件
3. `skills/career-search-operator/references/discovery_moves.md` — 所有合法 search moves（web_search、web_fetch、source routing 等）
4. `skills/career-search-operator/references/candidate_evidence_contract.md` — **最硬规则**：candidate 入池条件 + evidence path 要求
5. `skills/career-search-operator/references/data_policy_summary.md` — source / 存储 / budget 边界

`AGENTS.md`（项目边界）由平台自动注入；`protocols/AGENT_IO_CONTRACT.md` 是全局背景，需要细节时可查，但本 run 的全部要求已在上面 references 内。

## 流程（概览）

1. **读 task spec**（路径在 prompt 里）→ 拿到 `run_id`、`task_id`、`workspace_id`、`payload.discovery_intent`、`payload.budget`、`payload.output_paths`。详见 `discovery_io.md`。
2. **`career_search_status --task-spec <input.json 路径>`** 确认当前 budget 状态。**绝不 `career_search_session start`。**
3. **Discovery loop**（细则见 `discovery_moves.md` + `candidate_evidence_contract.md`）：
   自主选择 search moves → 执行 → log evidence → 调整策略 → 继续或停止。
   每 5 次 discovery action 后做一次 strategy self-review。
4. 写 **`coverage_report.md`** 到 `payload.output_paths.coverage_report_path`，然后调用 **`career_write_manifest`** 写 output manifest，然后 **STOP**。

## 硬性「不做」

- 不 `career_search_session start` / `end`（session 生命周期归平台）。
- 不跑 pipeline、不写 `db/jobs.jsonl`、不写 final job report。
- 不生成 Job Intelligence Report / Candidate Fit Report。
- 不调 `career_update_strategy`（strategy 由平台在 reflect 阶段更新）。
- 不登录平台、不绕过 paywall。
- 搜索只用 `web_search` **工具**；**不**用 `web_fetch` 抓 `google.com/search?...` 等搜索结果页代替搜索。
- 不用 `exec python3 -c` 或 heredoc 内联脚本——exec 只用于 `./wrappers/*`。

## 完成标志

`coverage_report.md` 已写到 `payload.output_paths.coverage_report_path`，`output_manifest.json` 已由 `career_write_manifest` 写到 `payload.output_paths.output_manifest_path`，且 run 里有至少一个真实 discovery action（`web_search` / `web_fetch` / `career_fetch_source`）——平台用 trace_events 里的真实 tool-call 做反捏造校验。
