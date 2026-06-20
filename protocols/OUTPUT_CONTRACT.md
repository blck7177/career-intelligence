# Output Contract

## Job Record 必须包含的字段

### 客观字段（来自 JD，不可推断）
- job_id: string（auto-generated）
- title: string
- company: string
- location: string
- source_url: string
- source_type: string（见 DATA_POLICY.md allowlist）
- date_found: ISO 8601 date
- raw_jd_path: string（相对路径到 runs/<timestamp>/raw_jds/<job_id>.txt）
- fetch_status: "success" | "failed" | "manual"

### 结构化字段（LLM 提取，需 evidence）
- responsibilities: list[string]
- required_skills: list[string]
- preferred_skills: list[string]
- tools_mentioned: list[string]
- finance_domains: list[string]
- seniority_inferred: string

### 分类字段（workstream classification）
- primary_workstream: string（必须是 workstream_taxonomy.yaml 中的枚举值）
- secondary_workstreams: list[string]
- classification_confidence: "high" | "medium" | "low"
- classification_evidence: list[string]（至少一条）
- uncertainty_notes: string | null

### 推断字段（LLM 推断，需标注来源）
- likely_tasks: list[string]
- likely_stakeholders: list[string]
- inferred_team_context: string
- evidence_from_jd: object（每个推断字段的 JD 证据片段）

### 元数据
- validation_status: "passed" | "failed"
- validation_errors: list[string]
- run_id: string
- schema_version: string

---

## 不确定性标记规范
- classification_confidence = "low" 时，uncertainty_notes 必填
- inferred 字段不能以确定性语气表述（用"likely", "appears to", "based on JD"）
- 禁止：模型无法从 JD 里找到证据时仍然填写字段值

---

## Run Summary 必须包含
- run_timestamp
- profile_used
- session_id
- jobs_discovered: int（candidate_pool 总数）
- jobs_fetched: int
- jobs_structured: int
- jobs_saved: int
- jobs_failed: int
- jobs_skipped: int
- top_workstreams: list（按频率排序）
- run_id

---

## 禁止输出
- 简历相关分析（resume fit, bullet mapping）
- 申请建议（apply recommendation）
- 候选人 PII
- 未标注来源的推断字段
