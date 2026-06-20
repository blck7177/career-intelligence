# User Context for career-search-agent

This agent is invoked by an automated platform worker, not a human.

Every invocation is bounded:
- A specific task spec is provided at a fixed path
- A specific output manifest path is expected
- A budget limits tool calls and candidate count
- A session key isolates this run from all other runs

There is no interactive user. Do not ask for clarification. If the task spec is ambiguous or incomplete, write a manifest with `status: failed` and `stop_reason` explaining what was missing.
