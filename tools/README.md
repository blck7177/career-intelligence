# Tools

Deterministic interfaces for agent and platform use.

## Structure

```
tools/
  wrappers/
    agent_tools/    # Python wrappers callable by OpenClaw (exec allowlist)
    platform_tools/ # Bash/Python wrappers for platform CLI operations
  cli/              # Click CLI entry points (pyproject.toml scripts)
  schemas/          # JSON Schema files for data contracts
```

## agent_tools/ Rules

- All wrappers accept only `--task-spec <path> --output <path>`
- No free-form arguments
- Input is validated before any side effects
- Output is always written to `--output` path (even on error)
- These are the ONLY commands in `agent/openclaw/config/exec-approvals.json`

## Adding a New Agent Tool

1. Create `tools/wrappers/agent_tools/career_<name>.py`
2. Use `--task-spec / --output` interface
3. Add to `agent/openclaw/config/exec-approvals.json` (requires human review)
4. Add to `agent/openclaw/agents/<agent>/TOOLS.md`
5. Write a test in `tests/contract/`
