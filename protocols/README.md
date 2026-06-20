# Protocol Index

Protocols define stable project rules. They override skill convenience instructions when there is a conflict.

## Available Protocols

| File | When to Read |
|------|-------------|
| `AGENT_IO_CONTRACT.md` | Before modifying worker/agent/service boundaries |
| `DATA_POLICY.md` | Before adding new data sources or storage patterns |
| `OUTPUT_CONTRACT.md` | Before changing field names in job records or reports |
| `PROJECT_PROTOCOL.md` | General project operating rules |
| `SEARCH_STRATEGY_PROTOCOL.md` | Before modifying discovery strategy logic |
| `WORKSTREAM_TAXONOMY.md` | Before changing job classification logic |
| `workflow_protocol.md` | Before changing task execution or run lifecycle |
| `review_protocol.md` | Before any change requiring human review |

## Source of Truth

Protocols override skill instructions. If a skill says one thing and a protocol says another, follow the protocol.

## Change Policy

Protocol changes require explicit human review. Agents may not modify protocol files autonomously.
