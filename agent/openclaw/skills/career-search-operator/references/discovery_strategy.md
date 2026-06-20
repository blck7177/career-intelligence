# Discovery Strategy

## 你拥有目标，不拥有步骤

你负责**达成发现目标**——在预算内最大化符合用户 intent 的 validated candidate supply——而不是执行固定 query 序列。

你的 discovery plan 是临时的。可以随时根据证据修改：搜索结果、fetch 到的页面、board sync 结果、缺失的候选、不相关结果、source 限制、新发现的术语。

持续区分三件事：
- **action completion**: 跑了一个 query、sync 了一个 board、fetch 了一个页面
- **objective progress**: 发现了有用的真实岗位候选
- **strategy failure**: 动作在完成，但目标没有推进

**不要优化 tool step 的完成数。优化 objective progress：新的相关候选、新的有用来源、或有真实 discovery action 支撑的明确 no-yield 解释。**

## 开始前：读 task spec 里的 catalog_context

`catalog_context` 告诉你：
- 已有多少岗位在库（`existing_job_count`）
- 最近已经发现了哪些公司（`recent_companies`）——这些公司已在库，不需要重复全量 sync
- Coverage gaps（`coverage_gaps`）——这次 run 应该优先补充的方向

**先读 context，再制定策略。不要从零开始。**

## 你可以自由改变

query family、source 策略、目标公司、术语、relevance 标准、探索深度、move 类型。

## 你不可以改变

- 数据边界（见 `data_policy_summary.md`）
- Evidence 要求（见 `candidate_evidence_contract.md`）
- 工具机制：搜索只能用 `web_search` 工具，不能用 `web_fetch` 抓搜索引擎结果页

## Board Sync 0-yield 后的强制 pivot

当 `career_sync_board` 返回 `would_keep=0` 或 `keep=0` 时：

1. 这是一个 **strategy failure 信号**，不是探索完成信号。
2. **不要立即写 coverage_report**。
3. 必须在停止前至少执行以下一项：
   - 同一 board 放宽或去掉 `--location-filter` 再试一次（确认是 filter 问题还是 board 本身无岗位）
   - 切换到 `company_boards.yaml` 里其他 `status: active` 的公司做 board_sync（Source Pivot）
   - 执行至少 1 次 `web_search`（Move 2 或 Move 4）寻找新来源

只有完成上述 pivot 且仍然 0 结果，才能将其归因为"真实 no-yield"并写入 coverage_report。

---

## 每 5 次 discovery action 后自评（简短）

每 5 次 discovery action 调一次 `career_search_status`，给自己回答（每条 1–2 句，不是给用户的汇报）：

1. 这 5 次 action 想找什么？
2. 尝试了哪些 move / source？
3. 找到几个真实岗位候选？board sync / web search 各贡献多少？
4. 哪些 move 没效果？failure mode？
5. 还缺哪些 workstream / company group / source type？
6. 下一步：继续、扩展、还是换方向？为什么？
7. 接下来具体做什么？

## 停止条件（任一满足）

1. 候选数量达到目标（通常 ≥20，或按 search_brief 给的更小目标）。
2. 主要 source families 已覆盖（board sync 已知公司 + web search 新公司）。
3. 连续 ≥3 次策略调整仍 0 新候选——记录 gap，结束。
4. Budget 耗尽（spec 的 `max_queries` / `max_pages` / `max_board_syncs`）。

满足后写 `coverage_report.md`（格式见 `candidate_evidence_contract.md` 末尾），然后 STOP。

## Strategy Notebook

在 `agent_work/drafts/strategy_state.md` 维护工作记录（随时修改，这是你的外部工作记忆）：

```markdown
# Discovery Strategy State
Session: <session_id>

## Current Objective
（本次 run 要发现什么类型的岗位）

## Catalog Context
（已有多少岗位在库，最近发现了哪些公司，coverage gaps 是什么）

## Current Working Hypothesis
（我认为哪些 move / source 最有可能找到目标岗位）

## What I Have Learned
（已观测到的：哪些 move 有效，哪些 source 有结果，哪些 URL 是真实 JD）

## What Is Not Working
（哪些方向效果差，为什么）

## Current Strategy Revision
（基于上面的观测，我现在的 discovery 方向是什么）

## Next Move
（下一步具体做什么：哪个 move，哪个公司/source/query）
```
