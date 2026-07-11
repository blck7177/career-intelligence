---
name: career-reflect-operator
description: "Bounded post-run reflection. Use when the platform asks you to reflect on an ALREADY-COMPLETED discovery run: diagnose failures/coverage, then write a strategy_patch.json + reflection_report.md. You do NOT write strategy_state.json, do NOT call career_update_strategy, do NOT run any pipeline."
---

# Career Reflect Operator

你是一个 **bounded reflection operator**。对**平台已经跑完的一次 discovery run** 做复盘，产出两个文件：机器可读的 `strategy_patch.json` 和人类可读的 `reflection_report.md`。你**不**写 `strategy_state.json`、**不**调 `career_update_strategy`、**不**跑任何 pipeline、**不**做 search。平台会校验你的 patch 并自己写回 strategy state。

```
Worker owns workflow + persistence.  Agent owns the bounded reflection.  Service applies the patch.
```

## 这个 skill 是 self-contained 的

执行本任务**只需读下面 3 个 skill-local references**（一跳直达，只服务本 bounded turn），外加确认合法 role category label 时读 `configs/role_category_taxonomy.yaml`：

1. `skills/career-reflect-operator/references/reflect_io.md` — 输入 spec、平台前后做什么、硬性「不做」
2. `skills/career-reflect-operator/references/strategy_patch_contract.md` — **字段白名单** + 合并语义 + coverage key 约束
3. `skills/career-reflect-operator/references/reflection_quality.md` — patch 与 report 的质量标准

`AGENTS.md` 由平台自动注入；`protocols/AGENT_IO_CONTRACT.md` 仍是全局背景，需要时可查。

## 流程（概览）

1. **读 input.json**（路径在 prompt 里）→ 拿到 `reflected_run_id`、artifact paths、`current_strategy_state`。
2. **读本轮结果**：用 read tool 读 `coverage_report_path` + `search_ledger_path`（不要用 exec 内联脚本）。
3. **诊断**：fetch failures（哪些源被墙）、role category coverage（sufficient/weak/missing）、query effectiveness（哪些 pattern 产出真实 JD URL）。
4. **写 `strategy_patch.json`**（字段与合并语义见 `strategy_patch_contract.md`；coverage key 必须是 taxonomy 合法 **id**；文件必须是 **flat 7 字段 object**，禁止 nested `patches` / `run_id` wrapper）。
5. **写 `reflection_report.md`**（质量标准见 `reflection_quality.md`）。
6. 调用 `career_write_manifest` 写 `output_manifest.json`（见下方 Wrapper Reference——**即使你判断这轮复盘做不出来**，也必须走这个 wrapper，不要用 `write` 工具直接写一个临时 JSON）。
7. **STOP**。

## Wrapper Reference

`career_write_manifest` 用 `exec` 调用：`--task-spec <json_file> --output <result_file>`。

正常完成：

```json
{
  "invocation_id": "<input.json 顶层 invocation_id>",
  "run_id": "<input.json 顶层 run_id，即 reflected_run_id 所属的那次 discovery run>",
  "task_id": "<input.json 顶层 task_id>",
  "status": "completed",
  "stop_reason": "reflection complete",
  "artifact_paths": {
    "reflection_report": "<你写 reflection_report.md 的实际路径>",
    "strategy_patch": "<你写 strategy_patch.json 的实际路径>"
  },
  "summary": {
    "patches_proposed": 5
  }
}
```

**判断这轮复盘做不出来时**（比如 artifact 内容不足、无法诊断），同样调用这个 wrapper，只是 `status`/`stop_reason` 不同——`invocation_id` 和 `run_id` 两个字段**在任何情况下都必须包含**，这两个字段一旦缺失，`output_manifest.json` 会在 `ReflectionManifest.model_validate()` 阶段直接报 `Field required` 而进 `needs_review`：

```json
{
  "invocation_id": "<input.json 顶层 invocation_id>",
  "run_id": "<input.json 顶层 run_id>",
  "task_id": "<input.json 顶层 task_id>",
  "status": "failed",
  "stop_reason": "<具体原因，例如: coverage_report.md 内容为空，无法诊断>",
  "artifact_paths": {},
  "summary": {}
}
```

不需要传 `output_paths` —— 省略时 wrapper 会用 `run_id`/`task_id`/默认 `artifacts_dir` 自动推出规范路径。

## 禁止行为（速查）

- 不写 `strategy_state.json`、不调 `career_update_strategy`（平台负责落库）。
- 不跑 pipeline、不做 search、不写 `db/jobs`。
- 不修改 `configs/`、`src/`（human-owned）。
- patch 里不得出现白名单以外的字段。
- **不要用 `write` 工具直接写 `output_manifest.json`**——包括"复盘做不出来"的情况——必须走 `career_write_manifest` wrapper，否则 `invocation_id`/`run_id` 大概率缺失，直接进 `needs_review`。

## 完成标志

`strategy_patch.json`、`reflection_report.md`、`output_manifest.json`（通过 `career_write_manifest` 写出）都已就位。
