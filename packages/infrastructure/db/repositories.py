"""
Repository layer — thin wrappers around SQLAlchemy queries.

Rules:
  - Each repository receives a Session from the caller (no session creation here)
  - No business logic — that belongs in packages/domain/
  - Repositories return ORM model instances; callers convert to Pydantic DTOs if needed
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from packages.infrastructure.db.models import (
    AgentInvocation,
    AgentToolEvent,
    AgentValidationResult,
    Artifact,
    Run,
    Task,
    TaskEvent,
    Workspace,
)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, workspace_id: str) -> Optional[Workspace]:
        return self._s.get(Workspace, workspace_id)

    def get_or_raise(self, workspace_id: str) -> Workspace:
        ws = self.get(workspace_id)
        if ws is None:
            raise ValueError(f"Workspace not found: {workspace_id}")
        return ws

    def create(self, *, name: str, workspace_id: Optional[str] = None) -> Workspace:
        ws = Workspace(name=name)
        if workspace_id:
            ws.id = workspace_id
        self._s.add(ws)
        self._s.flush()
        return ws


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class RunRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, run_id: str) -> Optional[Run]:
        return self._s.get(Run, run_id)

    def get_or_raise(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        return run

    def create(
        self,
        *,
        workspace_id: str,
        run_type: str,
        input_snapshot_json: dict | None = None,
        correlation_id: str | None = None,
    ) -> Run:
        run = Run(
            workspace_id=workspace_id,
            run_type=run_type,
            status="queued",
            input_snapshot_json=input_snapshot_json,
            correlation_id=correlation_id,
        )
        self._s.add(run)
        self._s.flush()
        return run

    def set_status(self, run_id: str, status: str) -> Run:
        run = self.get_or_raise(run_id)
        run.status = status
        self._s.flush()
        return run

    def list_for_workspace(self, workspace_id: str, limit: int = 50) -> list[Run]:
        return (
            self._s.query(Run)
            .filter(Run.workspace_id == workspace_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .all()
        )


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, task_id: str) -> Optional[Task]:
        return self._s.get(Task, task_id)

    def get_or_raise(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return task

    def create(
        self,
        *,
        run_id: str,
        workspace_id: str,
        task_type: str,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> Task:
        now = datetime.now(timezone.utc)
        task = Task(
            run_id=run_id,
            workspace_id=workspace_id,
            task_type=task_type,
            status="queued",
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            queued_at=now,
        )
        self._s.add(task)
        self._s.flush()
        return task

    def mark_running(self, task_id: str) -> Task:
        task = self.get_or_raise(task_id)
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        task.attempt_count += 1
        self._s.flush()
        return task

    def mark_succeeded(self, task_id: str) -> Task:
        task = self.get_or_raise(task_id)
        task.status = "succeeded"
        task.finished_at = datetime.now(timezone.utc)
        self._s.flush()
        return task

    def mark_failed(self, task_id: str, error_code: str, error_message: str) -> Task:
        task = self.get_or_raise(task_id)
        task.status = "failed"
        task.finished_at = datetime.now(timezone.utc)
        task.error_code = error_code
        task.error_message = error_message
        self._s.flush()
        return task

    def mark_needs_review(
        self,
        task_id: str,
        error_message: str,
        error_code: str | None = None,
    ) -> Task:
        task = self.get_or_raise(task_id)
        task.status = "needs_review"
        task.finished_at = datetime.now(timezone.utc)
        task.error_code = error_code
        task.error_message = error_message
        self._s.flush()
        return task

    def list_for_run(self, run_id: str) -> list[Task]:
        return (
            self._s.query(Task)
            .filter(Task.run_id == run_id)
            .order_by(Task.created_at)
            .all()
        )


# ---------------------------------------------------------------------------
# TaskEvent
# ---------------------------------------------------------------------------


class TaskEventRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def append(
        self,
        *,
        task_id: str,
        run_id: str,
        event_type: str,
        message: str | None = None,
        payload_json: dict | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            task_id=task_id,
            run_id=run_id,
            event_type=event_type,
            message=message,
            payload_json=payload_json,
        )
        self._s.add(event)
        self._s.flush()
        return event

    def list_for_run(self, run_id: str, limit: int = 200) -> list[TaskEvent]:
        return (
            self._s.query(TaskEvent)
            .filter(TaskEvent.run_id == run_id)
            .order_by(TaskEvent.created_at)
            .limit(limit)
            .all()
        )


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        run_id: str,
        task_id: str | None,
        artifact_type: str,
        storage_uri: str,
        content_hash: str | None = None,
        metadata_json: dict | None = None,
    ) -> Artifact:
        artifact = Artifact(
            run_id=run_id,
            task_id=task_id,
            artifact_type=artifact_type,
            storage_uri=storage_uri,
            content_hash=content_hash,
            metadata_json=metadata_json,
        )
        self._s.add(artifact)
        self._s.flush()
        return artifact

    def list_for_run(self, run_id: str) -> list[Artifact]:
        return (
            self._s.query(Artifact)
            .filter(Artifact.run_id == run_id)
            .order_by(Artifact.created_at)
            .all()
        )


# ---------------------------------------------------------------------------
# AgentInvocation
# ---------------------------------------------------------------------------


class AgentInvocationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        run_id: str,
        task_id: str,
        workspace_id: str,
        agent_id: str,
        session_key: str,
        skill_contract_version: str,
        input_spec_uri: str,
        output_manifest_uri: str,
    ) -> AgentInvocation:
        inv = AgentInvocation(
            run_id=run_id,
            task_id=task_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_key=session_key,
            skill_contract_version=skill_contract_version,
            status="pending",
            input_spec_uri=input_spec_uri,
            output_manifest_uri=output_manifest_uri,
        )
        self._s.add(inv)
        self._s.flush()
        return inv

    def mark_running(self, invocation_id: str) -> AgentInvocation:
        inv = self._s.get(AgentInvocation, invocation_id)
        if inv is None:
            raise ValueError(f"AgentInvocation not found: {invocation_id}")
        inv.status = "running"
        inv.started_at = datetime.now(timezone.utc)
        self._s.flush()
        return inv

    def mark_finished(
        self,
        invocation_id: str,
        *,
        exit_code: int,
        stdout_uri: str | None = None,
        stderr_uri: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AgentInvocation:
        inv = self._s.get(AgentInvocation, invocation_id)
        if inv is None:
            raise ValueError(f"AgentInvocation not found: {invocation_id}")
        inv.status = "succeeded" if exit_code == 0 else "failed"
        inv.finished_at = datetime.now(timezone.utc)
        inv.exit_code = exit_code
        inv.stdout_uri = stdout_uri
        inv.stderr_uri = stderr_uri
        inv.error_code = error_code
        inv.error_message = error_message
        self._s.flush()
        return inv

    def list_for_run(self, run_id: str) -> list[AgentInvocation]:
        return (
            self._s.query(AgentInvocation)
            .filter(AgentInvocation.run_id == run_id)
            .order_by(AgentInvocation.created_at)
            .all()
        )


# ---------------------------------------------------------------------------
# AgentToolEvent
# ---------------------------------------------------------------------------


class AgentToolEventRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def append(
        self,
        *,
        invocation_id: str,
        tool_name: str,
        action: str,
        input_hash: str | None = None,
        output_hash: str | None = None,
        status: str = "ok",
    ) -> AgentToolEvent:
        event = AgentToolEvent(
            invocation_id=invocation_id,
            tool_name=tool_name,
            action=action,
            input_hash=input_hash,
            output_hash=output_hash,
            status=status,
        )
        self._s.add(event)
        self._s.flush()
        return event


# ---------------------------------------------------------------------------
# AgentValidationResult
# ---------------------------------------------------------------------------


class AgentValidationResultRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        invocation_id: str,
        validator_name: str,
        status: str,
        errors_json: list | None = None,
        warnings_json: list | None = None,
    ) -> AgentValidationResult:
        result = AgentValidationResult(
            invocation_id=invocation_id,
            validator_name=validator_name,
            status=status,
            errors_json=errors_json,
            warnings_json=warnings_json,
        )
        self._s.add(result)
        self._s.flush()
        return result

    def list_for_invocation(self, invocation_id: str) -> list[AgentValidationResult]:
        return (
            self._s.query(AgentValidationResult)
            .filter(AgentValidationResult.invocation_id == invocation_id)
            .order_by(AgentValidationResult.created_at)
            .all()
        )
