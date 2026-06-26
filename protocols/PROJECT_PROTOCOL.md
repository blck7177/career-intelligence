# Project Protocol

## E2E Workflow

一次完整的 discovery run 分两个阶段。

---

## Phase 1: Search Session（agent-led, ledger-constrained）

详见 protocols/SEARCH_STRATEGY_PROTOCOL.md。

Search 是开放式探索，不是 deterministic pipeline。OpenClaw 使用 web search / web fetch 工具，
自主决定搜索策略。Repo 工具负责记录状态，不干涉搜索决策。

产出：`runs/<session_id>/candidate_pool.jsonl`

---

## Phase 2: Processing Pipeline（tool-enforced）

`career_run_discovery --from-candidates runs/<id>/candidate_pool.jsonl` 内部按顺序执行：

### Step 1: JD Fetch
- 对 candidate_pool 中每个岗位，获取 JD 原文
- 优先通过 source_url 直接 fetch
- fetch 失败时记录 fetch_status: failed，不跳过，继续下一个
- 原始 JD 文本保存到 runs/<timestamp>/raw_jds/<job_id>.txt

### Step 2: Role Research
- 对每个 job，补充公司 / 岗位上下文
- 允许：web search 公司公开信息、公开年报、公开新闻
- 禁止：登录平台、爬取非公开内容

### Step 3: Workstream Classification
- 对照 protocols/ROLE_CATEGORY_TAXONOMY.md 和 configs/role_category_taxonomy.yaml
- 确定 primary_role_category 和 secondary_role_categories
- 必须记录 classification_confidence 和 classification_evidence
- 不确定时，记录 uncertainty_notes，不强制归类

### Step 4: Structured Extraction
- 按照 schemas/job_record.schema.json 提取所有字段
- 所有 LLM 推断字段必须有 evidence_from_jd 来源标注
- 不能凭空推断字段值

### Step 5: Validation
- 调用 validator.py 验证每条 record 符合 schema
- validation 失败的 record 标记 validation_status: failed，不入库
- 记录 validation errors 到 runs/<timestamp>/validation_errors.jsonl

### Step 6: Save
- 通过 storage_jsonl.py 写入 db/jobs.jsonl（event-log 模式，always append）
- 更新 db/job_index.json（dedupe by url_hash，指向最新行）
- 重复 url_hash：upsert（追加新记录，index 更新指向最新行）

### Step 7: Run Artifact
- 生成 runs/<timestamp>/run_summary.md
- 生成 runs/<timestamp>/run_log.jsonl
- 生成 runs/<timestamp>/jobs_structured.json

---

## Partial Failure 处理
- 单个 job 失败不中断整个 run
- 每个失败记录原因到 run_log.jsonl
- run 完成后统计 success / failed / skipped 计数

## Run 命名规范
- 目录名：runs/YYYY-MM-DD_HHMMSS/
- run_config.yaml 记录：profile_name / actual_keywords / run_timestamp / runner_version
