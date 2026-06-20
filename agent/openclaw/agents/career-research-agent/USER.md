# Workspace Context — career-research-agent

## Workspace Purpose

This workspace runs bounded job research tasks. Each invocation researches one specific job
posting and the company behind it.

## Task Boundaries

- You research **one job per invocation**. Do not drift to other jobs.
- Research questions and the target job record are in your `input.json`.
- All output goes to the run directory specified in your task spec.
- You write `research_notes.md` (findings) and `research_sources.json` (all URLs cited).

## Run Directory Layout

```
/app/data/agent_artifacts/<run_id>/<task_id>/
  input.json                ← read this first
  output_manifest.json      ← write this last (via career_write_manifest)
  research_notes.md         ← your research findings
  research_sources.json     ← all cited URLs
```

## Session Isolation

Each invocation gets an isolated session key. Do not share state with other runs or workspaces.

## Stop Conditions

Stop and write the manifest when:
- All research questions are answered
- Budget (`max_tool_calls`) is exhausted
- You cannot make further progress (write `status: partial`)

## Evidence Standard

Every factual claim in `research_notes.md` must reference a URL in `research_sources.json`.
Do not speculate or infer beyond what sources support.
