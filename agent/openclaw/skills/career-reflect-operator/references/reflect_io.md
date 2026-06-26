# Reflect — I/O Contract (bounded)

> 全局契约见 `protocols/AGENT_IO_CONTRACT.md`。此处只保留 bounded reflection turn 需要的部分。

```
Worker owns workflow + persistence.  Agent owns the bounded reflection.  Service applies the patch.
```

## 输入：读 input.json（不要靠记忆）

平台在你的 prompt 里给一个 task spec 文件路径。用 read tool 读它：

```
/app/data/agent_artifacts/<reflection_run_id>/<reflection_task_id>/input.json
```

`payload` 字段（worker 已 enrich）：

```json
{
  "reflected_run_id": "<discovery run uuid>",
  "max_tool_calls": 10,
  "timeout_seconds": 300,
  "coverage_report_path": "/app/data/agent_artifacts/<discovery_run_id>/<discovery_task_id>/coverage_report.md",
  "search_ledger_path": "/app/data/agent_artifacts/<discovery_run_id>/<discovery_task_id>/search_ledger.jsonl",
  "candidate_pool_path": "/app/data/agent_artifacts/<discovery_run_id>/<discovery_task_id>/candidate_pool.jsonl",
  "reflected_run_summary": { "candidate_count": 12, "jobs_ingested": 8 },
  "current_strategy_state": { ... }
}
```

用 read tool 读 `coverage_report_path` 和 `search_ledger_path`（以及需要时的 `candidate_pool_path`）。**不要**依赖 legacy `runs/<session_id>/run_summary.md`（当前 worker 不生成该文件）。

## 平台在你之前已经做完的事

- 一次 discovery run **已经跑完**：search → validator → artifact 入库。
- Worker 已从 DB 查出被 reflect run 的 artifact 路径并写入 `input.json`。
- `current_strategy_state` 已从 `search_strategy_states` 表注入（首次 run 时为 null）。

## 你只做这一件事

对已完成的 run 做复盘，产出两个文件：
- `strategy_patch.json`（机器可读，字段受限，见 `strategy_patch_contract.md`）。
- `reflection_report.md`（人类可读，简短复盘）。

诊断重点：
- **Fetch Failures**：哪些 source 系统性失败（整源被墙）？应进 `avoid_sources` 吗？
- **Role Category Coverage**：哪些 sufficient / weak / missing？下一轮优先补哪个？
- **Query Effectiveness**：哪些 query pattern 产出真实 JD URL？哪些只返回 aggregator / 搜索结果页？

## 平台在你之后会做的事（你不要碰）

- `apply_strategy_patch` 校验你的 patch 字段（白名单），并作为 **`search_strategy_states` 的唯一写入者** 落库。
- 这是 best-effort：patch 不可读 / 字段非法会被拒绝，但**不会让 run 失败**。被拒就意味着你的复盘没生效。
- 下一轮 discovery run 的 `input.json` 会通过 `source_registry_snapshot` 和 `previous_run_diagnostics` 注入已 apply 的 hints。

## 完成标志（expected_outputs）

`strategy_patch.json` 和 `reflection_report.md` 都已写到 spec 指定路径。

## 硬性「不做」

- 不写 `strategy_state.json`、不调 `career_update_strategy`（落库归平台）。
- 不跑 processing pipeline、不做 search、不写 `db/jobs`。
- 不修改 `configs/`、`src/`（human-owned）。
- patch 里不得出现白名单以外的字段（见 `strategy_patch_contract.md`）。
