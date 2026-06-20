# Project Objective

## 1. Problem

Job seekers in specialized fields (e.g. quantitative finance, market risk) lack a systematic way to discover, research, and evaluate relevant job opportunities. Manual search across dozens of ATS boards and job sites is slow, incomplete, and produces unstructured data that is hard to track over time.

## 2. Target User

Individual professionals running active or exploratory job searches in specialized domains. Initially: quantitative finance / market risk roles in NYC.

## 3. MVP Scope

- Autonomous job discovery: given a search profile, find and ingest relevant job postings from known ATS boards and web sources
- Structured job database: normalize and store job records with extracted fields
- Job Intelligence Reports: deep per-job analysis (responsibilities, team signals, compensation signals, role fit indicators)
- Candidate Fit Reports: profile-specific match analysis per job
- Web platform: browse discovered jobs, view reports, trigger new discovery runs
- Agent-driven workflow: OpenClaw agents handle discovery, research, and reflection; deterministic workers handle persistence and validation

## 4. Non-Goals

- Resume writing or optimization
- Job application submission or outreach automation
- Career counseling or decision-making
- General-purpose job board aggregation (scope is specialized roles only)
- Multi-tenant SaaS (single user / single workspace for MVP)

## 5. Success Criteria

- A discovery run finds 10+ relevant new jobs per run across configured sources
- All discovered jobs have structured records with required fields populated
- Job Intelligence Reports cover all ingested jobs within 24 hours
- UI shows run status, job list, and reports without manual data wrangling
- Agent output always passes validation before entering the database
- System can run unattended: API accepts request, worker executes, UI shows results

## 6. Constraints

- OpenClaw agents are the only mechanism for non-deterministic work (search, research, reflection)
- OpenClaw must not write directly to the database; all output goes through a validator gate
- All agent execution is bounded by exec approvals (allowlist only)
- No credentials or DB connection strings are accessible to OpenClaw
- LLM API costs must be bounded per run (max_tool_calls enforced)
- Single-server Docker Compose deployment for production MVP

## 7. Future Extensions

- Multi-user workspaces with access control
- Additional job domains beyond quant finance
- Email/Slack notifications when new high-fit jobs appear
- Temporal-based workflow orchestration (replacing Celery for long workflows)
- Public API for third-party integrations
