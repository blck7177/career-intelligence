# Research Notes — 强制格式

> 来源：`protocols/ROLE_DOSSIER_PROTOCOL.md` 的 Research Notes 规范。校验器会按此格式逐源核对，缺字段的来源被降级为 unverified。

写到 spec 的 `expected_output_paths.research_notes` 路径。**最多 3 条 source；宁可少而精。** 聚焦 spec 的 `context_gaps`。

```markdown
# Research Notes — <company> (<job_id>)
Generated: <YYYY-MM-DD>

## Role-Specific Research Questions
(从 task spec 的 context_gaps 复制，作为本次 research 的聚焦目标)
- <question 1>

## Source Findings

### Source 1
- URL: <url>
- Source type: company_website | press_release | job_board | news | linkedin | other
- Relevant finding: <具体发现，只写 web_fetch 确认的内容，不写推测>
- Related JD signal: <这条 finding 对应 JD 里的哪个词 / 职责 / 团队名称>
- What this helps interpret: <它帮助解释了什么>
- Evidence strength: high | medium | low
- Boundary: <它不能证明什么>

## Synthesis for Job Report
- What research clarifies about the JD: <具体说明>
- What research does NOT clarify: <具体说明>
- Remaining uncertainty: <还有哪些问题没搜到>
```

## 格式硬规则

- 每条 finding 必须填 **`Related JD signal`** 和 **`Boundary`**，否则该来源在校验时被降级为 unverified（见 `source_verification_gate.md`）。
- `Relevant finding` 只写从 `web_fetch` 确认的内容，**不写推测**（推测留给生成报告的 LLM）。
- 不写未经 fetch 确认的来源——捏造会导致整个 bundle 判 failed。
