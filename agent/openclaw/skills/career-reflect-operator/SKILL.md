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

执行本任务**只需读下面 3 个 skill-local references**（一跳直达，只服务本 bounded turn），外加确认合法 workstream label 时读 `configs/workstream_taxonomy.yaml`：

1. `skills/career-reflect-operator/references/reflect_io.md` — 输入 spec、平台前后做什么、硬性「不做」
2. `skills/career-reflect-operator/references/strategy_patch_contract.md` — **字段白名单** + 合并语义 + coverage key 约束
3. `skills/career-reflect-operator/references/reflection_quality.md` — patch 与 report 的质量标准

`AGENTS.md` 由平台自动注入；`protocols/AGENT_IO_CONTRACT.md` 仍是全局背景，需要时可查。

## 流程（概览）

1. **读 task spec**（路径在 prompt 里）→ 拿到 `run_summary_path` / `coverage_report_path` / `expected_output_paths`。
2. **读本轮结果**：用 read tool 读 `run_summary.md` + `coverage_report.md`（不要用 exec 内联脚本）。
3. **诊断**：fetch failures（哪些源被墙）、workstream coverage（sufficient/weak/missing）、query effectiveness（哪些 pattern 产出真实 JD URL）。
4. **写 `strategy_patch.json`**（字段与合并语义见 `strategy_patch_contract.md`；coverage key 必须是 taxonomy 合法 label）。
5. **写 `reflection_report.md`**（质量标准见 `reflection_quality.md`）。
6. 两个文件都写到 spec 路径后 **STOP**。

## 禁止行为（速查）

- 不写 `strategy_state.json`、不调 `career_update_strategy`（平台负责落库）。
- 不跑 pipeline、不做 search、不写 `db/jobs`。
- 不修改 `configs/`、`src/`（human-owned）。
- patch 里不得出现白名单以外的字段。

## 完成标志

`strategy_patch.json` 和 `reflection_report.md` 都已写到 spec 指定路径。
