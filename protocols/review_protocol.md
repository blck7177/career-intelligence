# Review Protocol

## Human Review Required

The agent must stop and request human review before:

- Changing `protocols/` file meaning or scope
- Changing `PROJECT_OBJECTIVE.md`
- Broadening `agent/openclaw/config/exec-approvals.json` (adding new allowed commands)
- Giving OpenClaw access to DB credentials, internal APIs, or `.env`
- Loosening Validator Gate rules (removing checks, lowering thresholds)
- Dropping or modifying DB columns in a breaking way
- Changing data retention or deletion policy
- Any external write action (email, external API POST, etc.)
- Modifying `configs/` files directly (must use approved wrappers)

## Agent May Proceed Without Review

- Adding tests
- Adding documentation
- Adding new skills or updating skill instructions (not security-relevant)
- Creating non-destructive scripts or utilities
- Running dry-run validation
- Improving logging or observability
- Adding new API endpoints that read-only
- Adding new task types with deterministic handlers

## Review Gate Format

When stopping for review, the agent must output:

```
REVIEW REQUIRED

Reason: [one sentence]
Change proposed: [what would change]
Risk: [why this needs human review]
Recommended action: [what the human should decide]
```
