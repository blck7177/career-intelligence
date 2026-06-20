"""
Task event type constants.
Written to task_events table throughout execution.
"""

from __future__ import annotations


class TaskEventType:
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    ARTIFACT_WRITTEN = "artifact_written"
    AGENT_INVOCATION_STARTED = "agent_invocation_started"
    AGENT_INVOCATION_COMPLETED = "agent_invocation_completed"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    TASK_FAILED = "task_failed"
    TASK_SUCCEEDED = "task_succeeded"
    TASK_NEEDS_REVIEW = "task_needs_review"
