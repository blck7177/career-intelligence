# Workflow Protocol

## Task Lifecycle

All async work must go through the run/task state machine.

### State Machine

```
queued → running → succeeded
                 → failed
                 → needs_review
                 → cancelled
```

### Rules

1. API creates `run` and `task` records in Postgres before enqueueing
2. Worker claims task atomically — no double-claiming
3. task.attempt_count increments on each claim
4. max_attempts = 3 (configurable via env); exceeded → `failed`
5. `needs_review` is used when agent output fails validation — human review required before retry
6. `task_events` must be written at: task_claimed, step_started, step_completed, artifact_written, task_failed, task_succeeded
7. All runs must have an `input_snapshot_json` capturing user inputs at the time of submission

### Agent Task Rules

- Worker creates `agent_invocations` record before calling OpenClawRuntime
- `input.json` must be written to `agent_artifacts` volume before invocation
- Agent exit_code != 0 → mark invocation failed, task = needs_review
- Agent output must pass Validator Gate before any DB write
- `agent_validation_results` written regardless of pass/fail

### Idempotency

- Tasks include an `idempotency_key` (format: `{task_type}:{workspace_id}:{date}`)
- Duplicate submissions with same idempotency_key within TTL are rejected with 409

## Run Types

| run_type | task_types created |
|----------|-------------------|
| `job_discovery` | `agent.job_discovery` |
| `job_research` | `agent.job_research` per job |
| `job_report` | `job_report` per job |
| `fit_report` | `fit_report` per job |
| `run_reflection` | `agent.run_reflection` |
