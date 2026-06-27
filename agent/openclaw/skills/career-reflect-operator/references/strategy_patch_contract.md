# Strategy Patch — 字段契约

写到 spec 的 `expected_output_paths.strategy_patch` 路径。平台用一个**严格白名单**校验：出现任何白名单以外的字段，整个 patch 被拒（`StrategyPatchError`），你的复盘不生效。

## 只允许这 7 个字段（多一个就被拒）

```json
{
  "effective_sources": ["成功 fetch 的 source 描述，含类型或域名"],
  "avoid_sources": ["<domain> — <failure_reason: 403 / 404 / bot-blocked / login-required>"],
  "effective_query_patterns": ["产出真实 JD URL 的 query 模式"],
  "avoid_query_patterns": ["只返回搜索结果页的 query 模式"],
  "coverage_by_role_category": { "<role_category_label>": "sufficient | weak | missing" },
  "key_learnings": ["本轮新发现"],
  "recommended_next_searches": ["下一轮优先方向，对应 missing / weak role category"]
}
```

空 patch（`{}`）也合法。

## 格式要求（必读）

`strategy_patch.json` **必须是 flat object 本身**，不是 manifest、不是 operation list：

```json
{
  "effective_sources": ["boards.greenhouse.io — produced real JD URLs"],
  "avoid_sources": ["example.com — 403"]
}
```

**禁止**以下写法（会被拒或需 worker 兜底 normalize，仍可能丢字段）：

```json
{
  "run_id": "...",
  "patches": [
    { "field": "effective_sources", "action": "add", "value": ["..."] }
  ]
}
```

- 不要包 `run_id`、`invocation_id`、`patches`、`operations` 等 envelope 字段。
- manifest 的 `summary.patches_proposed` 是**计数**，与 `strategy_patch.json` 文件格式无关。
- 文件名虽叫 “patch”，内容是 **state delta object**（字段增量），不是 JSON Patch 操作列表。

## 合并语义（决定你写「增量」还是「全量」）

- **list 字段 union 合并**（累积，不替换）：`effective_sources`、`avoid_sources`、`effective_query_patterns`、`avoid_query_patterns`、`key_learnings`。→ 只写本轮**新增**的即可。
- **`recommended_next_searches` 整体替换**：写出你希望下一轮看到的**完整**列表。
- **`coverage_by_role_category` 按 key 更新**：只动你这轮有结论的 role category。

## coverage_by_role_category 的 key 约束

key **必须是 `configs/role_category_taxonomy.yaml` 里的合法 role category `id`**（value 取 `sufficient` / `weak` / `missing`）。平台在 `apply_strategy_patch()` 里有运行时校验：

- `id` 格式（如 `"market_risk_exposure"`）：直接接受。
- `label` 格式（如 `"Market Risk / Exposure Monitoring"`）：自动映射到对应 `id`。
- 既不是 `id` 也不是 `label` 的 key（如 `"Market Risk"`、`"Credit Analytics"`）：**patch 整体被拒**（`StrategyPatchError`）。

**始终使用 `id` 格式**（`label` 映射是为了向后兼容，不保证长期支持）。先读 `configs/role_category_taxonomy.yaml` 确认合法 id 再写。

合法 id 完整列表：
`market_risk_exposure` / `valuation_control_ipv` / `product_control_pnl` / `structured_credit` / `risk_analytics_automation` / `model_risk_validation` / `stress_testing` / `treasury_alm`
