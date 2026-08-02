"""
Repository layer — thin wrappers around SQLAlchemy queries.

Rules:
  - Each repository receives a Session from the caller (no session creation here)
  - No business logic — that belongs in packages/domain/
  - Repositories return ORM model instances; callers convert to Pydantic DTOs if needed
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from packages.infrastructure.db.models import (
    AgentInvocation,
    AgentToolEvent,
    AgentValidationResult,
    ApplicationAction,
    ApplicationEvent,
    Artifact,
    CandidateProfile,
    CompanySource,
    DeadUrl,
    FitReport,
    Job,
    JobApplication,
    JobFavorite,
    JobNotInterested,
    JobReport,
    LLMUsageEvent,
    PlannerDayLog,
    PlannerReview,
    Run,
    SearchStrategyStateRow,
    Task,
    TaskEvent,
    User,
    UserIdentity,
    Workspace,
    WorkspaceMember,
)
from packages.contracts.strategy.state import SearchStrategyState
from packages.domain.strategy_state import state_from_db_row, state_to_db_json


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_provider(self, provider: str, provider_user_id: str) -> Optional[User]:
        """Look up a local User by external provider identity."""
        from sqlalchemy import select
        stmt = (
            select(User)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .where(
                UserIdentity.provider == provider,
                UserIdentity.provider_user_id == provider_user_id,
            )
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def create(self, *, email: str) -> User:
        user = User(email=email)
        self._s.add(user)
        self._s.flush()
        return user


class UserIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        user_id: str,
        provider: str,
        provider_user_id: str,
        email: Optional[str] = None,
    ) -> UserIdentity:
        identity = UserIdentity(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
        )
        self._s.add(identity)
        self._s.flush()
        return identity


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, workspace_id: str) -> Optional[Workspace]:
        return self._s.get(Workspace, workspace_id)

    def get_for_update(self, workspace_id: str) -> Optional[Workspace]:
        """
        Row-lock this workspace for the rest of the current transaction.

        Used by create_run() to serialize its quota check-then-insert
        (count_this_month_for_workspace + RunRepository.create) per workspace,
        closing the race where concurrent requests all read the same
        under-limit count before any of them commits. See
        dev_note/career/phase20-launch-hardening/concurrency_test_0711/README.md
        for the real-concurrency test that demonstrated the race (8 concurrent
        requests, quota room for 1, all 8 created).

        Blocks the caller if another transaction already holds the lock
        (e.g. a concurrent create_run for the same workspace) until that
        transaction commits or rolls back — this is the intended effect.
        """
        return self._s.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().one_or_none()

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

    def get_for_user(self, user_id: str) -> Optional[Workspace]:
        """Return the first workspace the user is a member of."""
        from sqlalchemy import select
        stmt = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def add_member(self, *, workspace_id: str, user_id: str, role: str = "owner") -> WorkspaceMember:
        """Add a user as a workspace member."""
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        self._s.add(member)
        self._s.flush()
        return member

    def set_planner_settings(
        self, workspace_id: str, settings_json: dict
    ) -> Optional[Workspace]:
        """Overwrite the workspace's planner_settings_json with the given blob
        (the route has already merged partial edits over the stored value and
        validated the result). Returns None if the workspace is missing."""
        ws = self.get(workspace_id)
        if ws is None:
            return None
        ws.planner_settings_json = settings_json
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

    def set_result_summary(self, run_id: str, result_summary: dict) -> Run:
        run = self.get_or_raise(run_id)
        run.result_summary_json = result_summary
        self._s.flush()
        return run

    def complete(self, run_id: str, *, status: str, result_summary: dict) -> Run:
        """Set status and result_summary_json atomically in one flush."""
        run = self.get_or_raise(run_id)
        run.status = status
        run.result_summary_json = result_summary
        self._s.flush()
        return run

    def get_active_for_workspace(self, workspace_id: str, run_type: str) -> Optional[Run]:
        """
        Return the queued/running run of this type for this workspace, if any.
        Used to report the conflicting run when uq_active_agent_run_per_workspace_type
        rejects a duplicate insert.
        """
        return (
            self._s.query(Run)
            .filter(
                Run.workspace_id == workspace_id,
                Run.run_type == run_type,
                Run.status.in_(("queued", "running")),
            )
            .order_by(Run.created_at.desc())
            .first()
        )

    def count_this_month_for_workspace(self, workspace_id: str, run_type: str) -> int:
        """Count runs of this type created since the start of the current calendar month (UTC)."""
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return (
            self._s.query(Run)
            .filter(
                Run.workspace_id == workspace_id,
                Run.run_type == run_type,
                Run.created_at >= month_start,
            )
            .count()
        )

    def list_for_workspace(self, workspace_id: str, limit: int = 50) -> list[Run]:
        return (
            self._s.query(Run)
            .filter(Run.workspace_id == workspace_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_all(self, limit: int = 100, status: str | None = None) -> list[Run]:
        """Return runs across all workspaces (admin use only)."""
        q = self._s.query(Run)
        if status:
            q = q.filter(Run.status == status)
        return q.order_by(Run.created_at.desc()).limit(limit).all()


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

    def get(self, artifact_id: str) -> Optional[Artifact]:
        return self._s.get(Artifact, artifact_id)

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
        id: str | None = None,
    ) -> AgentInvocation:
        kwargs: dict = dict(
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
        if id is not None:
            kwargs["id"] = id
        inv = AgentInvocation(**kwargs)
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
        # Signed-ledger fields (optional for backward compatibility)
        event_id: str | None = None,
        sequence: int | None = None,
        prev_event_hash: str | None = None,
        event_hash: str | None = None,
        signature: str | None = None,
        raw_event_json: dict | None = None,
    ) -> AgentToolEvent:
        event = AgentToolEvent(
            invocation_id=invocation_id,
            tool_name=tool_name,
            action=action,
            input_hash=input_hash,
            output_hash=output_hash,
            status=status,
            event_id=event_id,
            sequence=sequence,
            prev_event_hash=prev_event_hash,
            event_hash=event_hash,
            signature=signature,
            raw_event_json=raw_event_json,
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


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

_COMPANY_SUFFIX_RE = re.compile(r"\s*[.,]?\s*&?\s*(co|inc|llc|ltd|corp|corporation)\.?$")


def _normalize_company_name(name: str) -> str:
    """
    Lowercase + strip punctuation and common corporate suffixes so
    "JPMorgan Chase" and "JPMorgan Chase & Co." compare equal. Company names
    are extracted independently per source and vary in formatting even for
    the same employer, so exact string matching under-detects duplicates.
    """
    n = name.lower().strip()
    n = re.sub(r"[.,]", "", n)
    n = _COMPANY_SUFFIX_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip()


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, job_id: str) -> Optional[Job]:
        return self._s.get(Job, job_id)

    def get_or_raise(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        return job

    def get_reportable(self, job_id: str) -> Job:
        """Return job only if status is 'reportable'. Raises ValueError otherwise."""
        job = self.get_or_raise(job_id)
        if job.status != "reportable":
            raise ValueError(
                f"Job {job_id} is not reportable (status={job.status!r}). "
                "Only jobs with status='reportable' can have reports generated."
            )
        return job

    def get_by_canonical_url(self, canonical_url: str) -> Optional[Job]:
        from sqlalchemy import select
        stmt = select(Job).where(Job.canonical_url == canonical_url)
        return self._s.execute(stmt).scalar_one_or_none()

    def list(
        self,
        *,
        run_ids: Optional[list[str]] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
        job_ids: Optional[set[str]] = None,
        exclude_source_types: Optional[list[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        """List jobs, optionally filtered by run_ids, status, and/or an explicit job_id set
        (the latter used for favorites_only). exclude_source_types drops rows by
        source_type (used to keep manual_paste jobs out of the discovery library)."""
        from sqlalchemy import select, func
        stmt = select(Job)
        if run_ids is not None:
            stmt = stmt.where(Job.discovered_run_id.in_(run_ids))
        if status:
            stmt = stmt.where(Job.status == status)
        elif not include_archived:
            stmt = stmt.where(Job.status != "archived")
        if job_ids is not None:
            stmt = stmt.where(Job.id.in_(job_ids))
        if exclude_source_types:
            stmt = stmt.where(Job.source_type.not_in(tuple(exclude_source_types)))
        stmt = stmt.order_by(Job.created_at.desc())
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self._s.execute(count_stmt).scalar_one()
        items = list(self._s.execute(stmt.offset(offset).limit(limit)).scalars().all())
        return items, total

    def create(
        self,
        *,
        canonical_url: str,
        source_url: str,
        source_type: str,
        source_provider: Optional[str] = None,
        title: str,
        company: str,
        jd_text: Optional[str] = None,
        jd_hash: Optional[str] = None,
        location: Optional[str] = None,
        raw_payload_json: Optional[dict] = None,
        status: str = "discovered",
        discovered_run_id: Optional[str] = None,
        discovered_task_id: Optional[str] = None,
        posted_at: Optional[datetime] = None,
    ) -> Job:
        job = Job(
            canonical_url=canonical_url,
            source_url=source_url,
            source_type=source_type,
            source_provider=source_provider,
            title=title,
            company=company,
            jd_text=jd_text,
            jd_hash=jd_hash,
            location=location,
            raw_payload_json=raw_payload_json,
            status=status,
            discovered_run_id=discovered_run_id,
            discovered_task_id=discovered_task_id,
            posted_at=posted_at,
        )
        self._s.add(job)
        self._s.flush()
        return job

    def set_status(self, job_id: str, status: str) -> None:
        job = self.get_or_raise(job_id)
        job.status = status
        self._s.flush()

    def update_jd(self, job_id: str, jd_text: str, jd_hash: str) -> None:
        """Backfill jd_text and jd_hash after a research run completes."""
        job = self.get_or_raise(job_id)
        job.jd_text = jd_text
        job.jd_hash = jd_hash
        self._s.flush()

    def merge_raw_payload(self, job_id: str, updates: dict) -> None:
        """Shallow-merge `updates` into the job's existing raw_payload_json."""
        job = self.get_or_raise(job_id)
        job.raw_payload_json = {**(job.raw_payload_json or {}), **updates}
        self._s.flush()

    def has_company_title_collision(self, company: str, title: str, exclude_job_id: str) -> bool:
        """
        True if another job (different id) shares the same title at what
        looks like the same company (see _normalize_company_name — company
        names vary in formatting per source, e.g. "JPMorgan Chase" vs
        "JPMorgan Chase & Co.", so this isn't an exact string match).

        Used to gate auto-promotion of research-backfilled JD text: fetched
        text can't be reliably tied to one specific posting when the employer
        has multiple concurrent postings with an identical title (e.g.
        several req numbers for the same role name).
        """
        from sqlalchemy import select
        stmt = select(Job.company).where(
            Job.title == title,
            Job.id != exclude_job_id,
        )
        target = _normalize_company_name(company)
        return any(
            _normalize_company_name(other_company) == target
            for (other_company,) in self._s.execute(stmt).all()
        )


# ---------------------------------------------------------------------------
# JobFavorite — workspace-private bookmark on a (global) job
# ---------------------------------------------------------------------------


class JobFavoriteRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def is_favorited(self, workspace_id: str, job_id: str) -> bool:
        from sqlalchemy import select

        stmt = select(JobFavorite.id).where(
            JobFavorite.workspace_id == workspace_id,
            JobFavorite.job_id == job_id,
        )
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def list_job_ids_for_workspace(self, workspace_id: str) -> set[str]:
        from sqlalchemy import select

        stmt = select(JobFavorite.job_id).where(JobFavorite.workspace_id == workspace_id)
        return set(self._s.execute(stmt).scalars().all())

    def add(self, workspace_id: str, job_id: str) -> None:
        if self.is_favorited(workspace_id, job_id):
            return
        self._s.add(JobFavorite(workspace_id=workspace_id, job_id=job_id))
        self._s.flush()

    def remove(self, workspace_id: str, job_id: str) -> None:
        from sqlalchemy import delete

        stmt = delete(JobFavorite).where(
            JobFavorite.workspace_id == workspace_id,
            JobFavorite.job_id == job_id,
        )
        self._s.execute(stmt)
        self._s.flush()


# ---------------------------------------------------------------------------
# JobNotInterested — workspace-private dismissal of a (global) job
# ---------------------------------------------------------------------------


class JobNotInterestedRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def is_not_interested(self, workspace_id: str, job_id: str) -> bool:
        from sqlalchemy import select

        stmt = select(JobNotInterested.id).where(
            JobNotInterested.workspace_id == workspace_id,
            JobNotInterested.job_id == job_id,
        )
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def list_job_ids_for_workspace(self, workspace_id: str) -> set[str]:
        from sqlalchemy import select

        stmt = select(JobNotInterested.job_id).where(JobNotInterested.workspace_id == workspace_id)
        return set(self._s.execute(stmt).scalars().all())

    def add(self, workspace_id: str, job_id: str) -> None:
        if self.is_not_interested(workspace_id, job_id):
            return
        self._s.add(JobNotInterested(workspace_id=workspace_id, job_id=job_id))
        self._s.flush()

    def remove(self, workspace_id: str, job_id: str) -> None:
        from sqlalchemy import delete

        stmt = delete(JobNotInterested).where(
            JobNotInterested.workspace_id == workspace_id,
            JobNotInterested.job_id == job_id,
        )
        self._s.execute(stmt)
        self._s.flush()


# ---------------------------------------------------------------------------
# DeadUrl
# ---------------------------------------------------------------------------


class DeadUrlRepository:
    """Records URLs confirmed dead on arrival and answers negative-cache lookups.

    ``url`` is expected already normalized (url_normalize.normalize_job_url);
    the hash matches jd_fetch.compute_url_hash (md5[:16]) so lookups agree with
    the artifact cache key.
    """

    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _hash(url: str) -> str:
        import hashlib

        return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]

    def is_dead(self, url: str) -> bool:
        from sqlalchemy import select

        stmt = select(DeadUrl.id).where(DeadUrl.url_hash == self._hash(url))
        return self._s.execute(stmt).scalar_one_or_none() is not None

    def record(
        self,
        *,
        url: str,
        reason: str,
        http_status: Optional[int] = None,
        discovered_run_id: Optional[str] = None,
    ) -> DeadUrl:
        from urllib.parse import urlparse

        from sqlalchemy import select

        h = self._hash(url)
        existing = self._s.execute(
            select(DeadUrl).where(DeadUrl.url_hash == h)
        ).scalar_one_or_none()
        if existing is not None:
            existing.times_seen += 1
            existing.last_seen_at = datetime.now(timezone.utc)
            self._s.flush()
            return existing
        dead = DeadUrl(
            url_hash=h,
            canonical_url=url[:2048],
            domain=urlparse(url).hostname or None,
            reason=reason,
            http_status=http_status,
            discovered_run_id=discovered_run_id,
        )
        self._s.add(dead)
        self._s.flush()
        return dead

    def touch(self, url: str) -> None:
        """Negative-cache hit on an already-recorded dead URL: bump counters
        without needing the (unchanged) reason."""
        from sqlalchemy import select

        existing = self._s.execute(
            select(DeadUrl).where(DeadUrl.url_hash == self._hash(url))
        ).scalar_one_or_none()
        if existing is not None:
            existing.times_seen += 1
            existing.last_seen_at = datetime.now(timezone.utc)
            self._s.flush()


# ---------------------------------------------------------------------------
# JobReport
# ---------------------------------------------------------------------------


class JobReportRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, report_id: str) -> Optional[JobReport]:
        return self._s.get(JobReport, report_id)

    def get_active(
        self,
        job_id: str,
        jd_hash: str,
        prompt_version: str,
        research_bundle_hash: str,
    ) -> Optional[JobReport]:
        """Return an active cached report matching exact cache key, or None."""
        from sqlalchemy import select
        stmt = (
            select(JobReport)
            .where(
                JobReport.job_id == job_id,
                JobReport.jd_hash == jd_hash,
                JobReport.prompt_version == prompt_version,
                JobReport.research_bundle_hash == research_bundle_hash,
                JobReport.status == "active",
            )
            .order_by(JobReport.created_at.desc())
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def get_latest_active(self, job_id: str) -> Optional[JobReport]:
        """Return the most recent active report for a job, regardless of cache key."""
        from sqlalchemy import select
        stmt = (
            select(JobReport)
            .where(JobReport.job_id == job_id, JobReport.status == "active")
            .order_by(JobReport.created_at.desc())
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def supersede_prior(self, job_id: str) -> None:
        """Mark all existing active reports for this job as superseded."""
        from sqlalchemy import update
        now = datetime.now(timezone.utc)
        stmt = (
            update(JobReport)
            .where(JobReport.job_id == job_id, JobReport.status == "active")
            .values(status="superseded", superseded_at=now, updated_at=now)
        )
        self._s.execute(stmt)
        self._s.flush()

    def create(
        self,
        *,
        job_id: str,
        jd_hash: str,
        prompt_version: str,
        analysis_version: str = "1.0",
        used_research: bool = False,
        research_artifact_id: Optional[str] = None,
        research_bundle_hash: str = "none",
        narrative_artifact_id: Optional[str] = None,
        structured_artifact_id: Optional[str] = None,
        structured_json: Optional[dict] = None,
        summary_json: Optional[dict] = None,
        status: str = "active",
        id: str | None = None,
    ) -> JobReport:
        kwargs: dict = dict(
            job_id=job_id,
            jd_hash=jd_hash,
            prompt_version=prompt_version,
            analysis_version=analysis_version,
            used_research=used_research,
            research_artifact_id=research_artifact_id,
            research_bundle_hash=research_bundle_hash,
            narrative_artifact_id=narrative_artifact_id,
            structured_artifact_id=structured_artifact_id,
            structured_json=structured_json,
            summary_json=summary_json,
            status=status,
        )
        if id is not None:
            kwargs["id"] = id
        row = JobReport(**kwargs)
        self._s.add(row)
        self._s.flush()
        return row

    def get_latest_active_map(self, job_ids: list[str]) -> dict[str, JobReport]:
        """Return the latest active job report per job_id."""
        if not job_ids:
            return {}
        from sqlalchemy import func, select

        subq = (
            select(
                JobReport.job_id,
                func.max(JobReport.created_at).label("max_created"),
            )
            .where(JobReport.job_id.in_(job_ids), JobReport.status == "active")
            .group_by(JobReport.job_id)
            .subquery()
        )
        stmt = select(JobReport).join(
            subq,
            (JobReport.job_id == subq.c.job_id)
            & (JobReport.created_at == subq.c.max_created),
        )
        rows = self._s.execute(stmt).scalars().all()
        return {row.job_id: row for row in rows}


# ---------------------------------------------------------------------------
# FitReport
# ---------------------------------------------------------------------------


class FitReportRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, report_id: str) -> Optional[FitReport]:
        return self._s.get(FitReport, report_id)

    def list_summaries_for_workspace(
        self,
        *,
        workspace_id: str,
        profile_id: Optional[str] = None,
        status: str = "active",
        limit: int = 500,
    ) -> list[FitReport]:
        """List fit reports for inbox overlay; latest per job_id first."""
        from sqlalchemy import select

        stmt = select(FitReport).where(
            FitReport.workspace_id == workspace_id,
            FitReport.status == status,
        )
        if profile_id:
            stmt = stmt.where(FitReport.candidate_profile_id == profile_id)
        stmt = stmt.order_by(FitReport.updated_at.desc()).limit(limit)
        rows = list(self._s.execute(stmt).scalars().all())
        seen: set[str] = set()
        deduped: list[FitReport] = []
        for row in rows:
            if row.job_id in seen:
                continue
            seen.add(row.job_id)
            deduped.append(row)
        return deduped

    def get_active(
        self,
        *,
        workspace_id: str,
        job_id: str,
        job_report_id: str,
        candidate_profile_id: Optional[str],
        profile_hash: str,
        prompt_version: str,
    ) -> Optional[FitReport]:
        """Return active cached fit report matching exact cache key, or None."""
        from sqlalchemy import select
        stmt = (
            select(FitReport)
            .where(
                FitReport.workspace_id == workspace_id,
                FitReport.job_id == job_id,
                FitReport.job_report_id == job_report_id,
                FitReport.candidate_profile_id == candidate_profile_id,
                FitReport.profile_hash == profile_hash,
                FitReport.prompt_version == prompt_version,
                FitReport.status == "active",
            )
            .order_by(FitReport.created_at.desc())
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def get_latest_for_job(
        self, *, workspace_id: str, job_id: str, profile_id: Optional[str] = None
    ) -> Optional[FitReport]:
        """Most recent active fit report for a job in this workspace (optionally
        profile-scoped) — powers the application detail's Fit badge."""
        from sqlalchemy import select

        stmt = select(FitReport).where(
            FitReport.workspace_id == workspace_id,
            FitReport.job_id == job_id,
            FitReport.status == "active",
        )
        if profile_id:
            stmt = stmt.where(FitReport.candidate_profile_id == profile_id)
        stmt = stmt.order_by(FitReport.updated_at.desc()).limit(1)
        return self._s.execute(stmt).scalar_one_or_none()

    def latest_score_map(
        self, workspace_id: str, job_ids: list[str], profile_id: Optional[str] = None
    ) -> dict[str, int]:
        """{job_id: latest active overall_match_score} for the given jobs — one
        batched query (newest-per-job wins). Powers the planned queue's Fit
        column without a per-row lookup."""
        if not job_ids:
            return {}
        from sqlalchemy import select

        stmt = select(FitReport).where(
            FitReport.workspace_id == workspace_id,
            FitReport.job_id.in_(job_ids),
            FitReport.status == "active",
        )
        if profile_id:
            stmt = stmt.where(FitReport.candidate_profile_id == profile_id)
        stmt = stmt.order_by(FitReport.updated_at.desc())
        out: dict[str, int] = {}
        for r in self._s.execute(stmt).scalars().all():
            # ordered newest-first → first seen per job is the latest.
            if r.job_id not in out and r.overall_match_score is not None:
                out[r.job_id] = r.overall_match_score
        return out

    def supersede_prior(
        self,
        *,
        workspace_id: str,
        job_id: str,
        candidate_profile_id: Optional[str],
        profile_hash: str,
    ) -> None:
        from sqlalchemy import update
        now = datetime.now(timezone.utc)
        stmt = (
            update(FitReport)
            .where(
                FitReport.workspace_id == workspace_id,
                FitReport.job_id == job_id,
                FitReport.profile_hash == profile_hash,
                FitReport.status == "active",
            )
            .values(status="superseded", superseded_at=now, updated_at=now)
        )
        self._s.execute(stmt)
        self._s.flush()

    def create(
        self,
        *,
        workspace_id: str,
        job_id: str,
        job_report_id: str,
        candidate_profile_id: Optional[str] = None,
        profile_hash: str,
        prompt_version: str,
        overall_match_score: int = 0,
        structured_artifact_id: Optional[str] = None,
        narrative_artifact_id: Optional[str] = None,
        structured_json: Optional[dict] = None,
        summary_json: Optional[dict] = None,
        status: str = "active",
        id: str | None = None,
    ) -> FitReport:
        kwargs: dict = dict(
            workspace_id=workspace_id,
            job_id=job_id,
            job_report_id=job_report_id,
            candidate_profile_id=candidate_profile_id,
            profile_hash=profile_hash,
            prompt_version=prompt_version,
            overall_match_score=overall_match_score,
            structured_artifact_id=structured_artifact_id,
            narrative_artifact_id=narrative_artifact_id,
            structured_json=structured_json,
            summary_json=summary_json,
            status=status,
        )
        if id is not None:
            kwargs["id"] = id
        row = FitReport(**kwargs)
        self._s.add(row)
        self._s.flush()
        return row


# ---------------------------------------------------------------------------
# CandidateProfile
# ---------------------------------------------------------------------------


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_for_workspace(self, workspace_id: str) -> Optional[CandidateProfile]:
        """Return the most recently updated profile for the workspace (default profile)."""
        return (
            self._s.query(CandidateProfile)
            .filter(CandidateProfile.workspace_id == workspace_id)
            .order_by(CandidateProfile.updated_at.desc())
            .first()
        )

    def get_by_id(self, profile_id: str) -> Optional[CandidateProfile]:
        return self._s.query(CandidateProfile).filter(CandidateProfile.id == profile_id).first()

    def list_for_workspace(self, workspace_id: str) -> list[CandidateProfile]:
        return (
            self._s.query(CandidateProfile)
            .filter(CandidateProfile.workspace_id == workspace_id)
            .order_by(CandidateProfile.updated_at.desc())
            .all()
        )

    def count_for_workspace(self, workspace_id: str) -> int:
        return (
            self._s.query(CandidateProfile)
            .filter(CandidateProfile.workspace_id == workspace_id)
            .count()
        )

    def create(
        self,
        workspace_id: str,
        *,
        label: str = "",
        summary: Optional[str] = None,
        experience_summary: Optional[str] = None,
        education_summary: Optional[str] = None,
        technical_skills: Optional[list] = None,
        subject_areas: Optional[list] = None,
        tools: Optional[list] = None,
        representative_projects: Optional[list] = None,
        years_experience: Optional[int] = None,
        profile_hash: str = "empty",
        structured_resume_json: Optional[dict] = None,
    ) -> CandidateProfile:
        profile = CandidateProfile(workspace_id=workspace_id)
        profile.label = label
        profile.summary = summary
        profile.experience_summary = experience_summary
        profile.education_summary = education_summary
        profile.technical_skills = technical_skills
        profile.subject_areas = subject_areas
        profile.tools = tools
        profile.representative_projects = representative_projects
        profile.years_experience = years_experience
        profile.profile_hash = profile_hash
        profile.structured_resume_json = structured_resume_json
        self._s.add(profile)
        self._s.flush()
        return profile

    def update(
        self,
        profile_id: str,
        *,
        label: Optional[str] = None,
        summary: Optional[str] = None,
        experience_summary: Optional[str] = None,
        education_summary: Optional[str] = None,
        technical_skills: Optional[list] = None,
        subject_areas: Optional[list] = None,
        tools: Optional[list] = None,
        representative_projects: Optional[list] = None,
        years_experience: Optional[int] = None,
        profile_hash: str = "empty",
        structured_resume_json: Optional[dict] = None,
    ) -> CandidateProfile:
        profile = self.get_by_id(profile_id)
        if profile is None:
            raise ValueError(f"Profile {profile_id!r} not found")
        if label is not None:
            profile.label = label
        profile.summary = summary
        profile.experience_summary = experience_summary
        profile.education_summary = education_summary
        profile.technical_skills = technical_skills
        profile.subject_areas = subject_areas
        profile.tools = tools
        profile.representative_projects = representative_projects
        profile.years_experience = years_experience
        profile.profile_hash = profile_hash
        # Guarded (unlike the fields above, which are always fully replaced):
        # an ordinary field edit that doesn't resubmit the imported resume's
        # structured data must not silently wipe it. Matches upsert()'s
        # existing guard for the same field.
        if structured_resume_json is not None:
            profile.structured_resume_json = structured_resume_json
        self._s.flush()
        return profile

    def delete(self, profile_id: str) -> None:
        profile = self.get_by_id(profile_id)
        if profile is not None:
            self._s.delete(profile)
            self._s.flush()

    def update_search_defaults(self, profile_id: str, defaults: dict) -> None:
        profile = self.get_by_id(profile_id)
        if profile is not None:
            profile.search_defaults = defaults
            self._s.flush()

    def upsert(
        self,
        workspace_id: str,
        *,
        summary: Optional[str] = None,
        experience_summary: Optional[str] = None,
        education_summary: Optional[str] = None,
        technical_skills: Optional[list] = None,
        subject_areas: Optional[list] = None,
        tools: Optional[list] = None,
        representative_projects: Optional[list] = None,
        years_experience: Optional[int] = None,
        profile_hash: str = "empty",
        structured_resume_json: Optional[dict] = None,
    ) -> CandidateProfile:
        """Create or update the default (most recent) profile for a workspace."""
        profile = self.get_for_workspace(workspace_id)
        if profile is None:
            profile = CandidateProfile(workspace_id=workspace_id)
            self._s.add(profile)

        profile.summary = summary
        profile.experience_summary = experience_summary
        profile.education_summary = education_summary
        profile.technical_skills = technical_skills
        profile.subject_areas = subject_areas
        profile.tools = tools
        profile.representative_projects = representative_projects
        profile.years_experience = years_experience
        profile.profile_hash = profile_hash
        if structured_resume_json is not None:
            profile.structured_resume_json = structured_resume_json

        self._s.flush()
        return profile


# ---------------------------------------------------------------------------
# SearchStrategyState
# ---------------------------------------------------------------------------


class SearchStrategyStateRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_for_workspace(self, workspace_id: str) -> Optional[SearchStrategyState]:
        row = (
            self._s.query(SearchStrategyStateRow)
            .filter(SearchStrategyStateRow.workspace_id == workspace_id)
            .first()
        )
        if row is None:
            return None
        return state_from_db_row(
            workspace_id=row.workspace_id,
            profile_id=row.profile_id,
            state_json=row.state_json or {},
            last_reflection_run_id=row.last_reflection_run_id,
            last_reflection_task_id=row.last_reflection_task_id,
            updated_at=row.updated_at,
        )

    def upsert(self, state: SearchStrategyState) -> SearchStrategyState:
        row = (
            self._s.query(SearchStrategyStateRow)
            .filter(SearchStrategyStateRow.workspace_id == state.workspace_id)
            .first()
        )
        if row is None:
            row = SearchStrategyStateRow(workspace_id=state.workspace_id)
            self._s.add(row)

        row.profile_id = state.profile_id
        row.state_json = state_to_db_json(state)
        row.last_reflection_run_id = state.last_reflection_run_id
        row.last_reflection_task_id = state.last_reflection_task_id
        row.updated_at = state.updated_at or datetime.now(timezone.utc)

        self._s.flush()
        return state_from_db_row(
            workspace_id=row.workspace_id,
            profile_id=row.profile_id,
            state_json=row.state_json or {},
            last_reflection_run_id=row.last_reflection_run_id,
            last_reflection_task_id=row.last_reflection_task_id,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# Company Sources (ATS board registry)
# ---------------------------------------------------------------------------


class CompanySourceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_by_board(self, provider: str, token: str) -> Optional[CompanySource]:
        return (
            self._s.query(CompanySource)
            .filter(CompanySource.ats_provider == provider, CompanySource.board_token == token)
            .first()
        )

    def list_syncable(self) -> list[CompanySource]:
        return (
            self._s.query(CompanySource)
            .filter(CompanySource.status.in_(("verified", "active")))
            .all()
        )

    def list_known(self) -> list[CompanySource]:
        """All non-blocked boards, plus blocked boards older than 7 days (auto-retry)."""
        from sqlalchemy import or_
        retry_cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)
        return (
            self._s.query(CompanySource)
            .filter(
                or_(
                    CompanySource.status.in_(("verified", "active", "discovered")),
                    # blocked boards become retryable after 7 days
                    (CompanySource.status == "blocked") & (CompanySource.updated_at < retry_cutoff),
                )
            )
            .all()
        )

    def create(
        self,
        *,
        company_name: str,
        ats_provider: str,
        board_token: str,
        board_api_url: str | None = None,
        board_careers_url: str | None = None,
        status: str = "discovered",
        discovered_run_id: str | None = None,
        workspace_id: str | None = None,
        last_verified_at: datetime | None = None,
        metadata_json: dict | None = None,
    ) -> CompanySource:
        row = CompanySource(
            workspace_id=workspace_id,
            company_name=company_name,
            ats_provider=ats_provider,
            board_token=board_token,
            board_api_url=board_api_url,
            board_careers_url=board_careers_url,
            status=status,
            discovered_run_id=discovered_run_id,
            last_verified_at=last_verified_at,
            metadata_json=metadata_json,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def update_sync_result(
        self,
        source_id: str,
        *,
        job_count: int,
        sync_at: datetime,
        status: str | None = None,
    ) -> None:
        row = self._s.query(CompanySource).get(source_id)
        if row is None:
            return
        row.last_sync_at = sync_at
        row.job_count_last_sync = job_count
        if status:
            row.status = status
        self._s.flush()

    def set_status(self, source_id: str, status: str) -> None:
        row = self._s.query(CompanySource).get(source_id)
        if row is None:
            return
        row.status = status
        self._s.flush()


# ---------------------------------------------------------------------------
# LLM Usage
# ---------------------------------------------------------------------------


class LLMUsageEventRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list_for_run(self, run_id: str) -> list[LLMUsageEvent]:
        return (
            self._s.query(LLMUsageEvent)
            .filter(LLMUsageEvent.run_id == run_id)
            .order_by(LLMUsageEvent.created_at)
            .all()
        )

    def summary_by_run_type(
        self, *, limit: int = 100
    ) -> list[dict]:
        """Aggregate cost by run_type. Returns list of dicts."""
        from sqlalchemy import func as sa_func

        rows = (
            self._s.query(
                Run.run_type,
                sa_func.count(LLMUsageEvent.id).label("llm_calls"),
                sa_func.sum(LLMUsageEvent.prompt_tokens).label("prompt_tokens"),
                sa_func.sum(LLMUsageEvent.completion_tokens).label("completion_tokens"),
                sa_func.sum(LLMUsageEvent.total_tokens).label("total_tokens"),
                sa_func.sum(LLMUsageEvent.estimated_cost_usd).label("estimated_cost_usd"),
            )
            .join(Run, LLMUsageEvent.run_id == Run.id)
            .group_by(Run.run_type)
            .order_by(sa_func.sum(LLMUsageEvent.estimated_cost_usd).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_type": r.run_type,
                "llm_calls": r.llm_calls,
                "prompt_tokens": r.prompt_tokens or 0,
                "completion_tokens": r.completion_tokens or 0,
                "total_tokens": r.total_tokens or 0,
                "estimated_cost_usd": round(r.estimated_cost_usd or 0, 6),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Application Tracker — job_applications / application_events / application_actions
# ---------------------------------------------------------------------------


class JobApplicationRepository:
    """Workspace-private application rows. Every read is workspace-scoped
    (get/list take workspace_id) to keep the IDOR surface closed — see the
    launch-hardening notes. flush-never-commit, like the other repos."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        workspace_id: str,
        job_id: str,
        profile_id: str | None = None,
        status: str = "planned",
        lane: str | None = None,
        excitement: int | None = None,
        channel: str | None = None,
        applied_at: datetime | None = None,
        resume_run_id: str | None = None,
        contact_name: str | None = None,
        contact_note: str | None = None,
        notes: str | None = None,
    ) -> JobApplication:
        # job_id is required — every application references a job row (URL-imported
        # or created from a pasted JD via the shared manual_import pipeline). There
        # are no bare/off-platform applications.
        row = JobApplication(
            workspace_id=workspace_id,
            job_id=job_id,
            profile_id=profile_id,
            status=status,
            lane=lane,
            excitement=excitement,
            channel=channel,
            applied_at=applied_at,
            resume_run_id=resume_run_id,
            contact_name=contact_name,
            contact_note=contact_note,
            notes=notes,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, application_id: str, workspace_id: str) -> Optional[JobApplication]:
        from sqlalchemy import select

        stmt = select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.workspace_id == workspace_id,
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def get_by_job(self, workspace_id: str, job_id: str) -> Optional[JobApplication]:
        """The application for a (workspace, job), if one exists — enforces the
        one-application-per-job rule at the API layer with a clean 409."""
        from sqlalchemy import select

        stmt = select(JobApplication).where(
            JobApplication.workspace_id == workspace_id,
            JobApplication.job_id == job_id,
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        status_group: str | None = None,
        needs_action: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobApplication]:
        from sqlalchemy import or_, select

        from packages.domain.applications.transitions import STATUS_GROUPS

        stmt = select(JobApplication).where(JobApplication.workspace_id == workspace_id)
        if status_group:
            statuses = STATUS_GROUPS.get(status_group)
            if statuses is not None:
                stmt = stmt.where(JobApplication.status.in_(tuple(statuses)))
        if needs_action:
            now = datetime.now(timezone.utc)
            due_ids = (
                select(ApplicationAction.application_id)
                .where(
                    ApplicationAction.workspace_id == workspace_id,
                    ApplicationAction.application_id.is_not(None),
                    ApplicationAction.status == "pending",
                    or_(
                        ApplicationAction.due_at.is_(None),
                        ApplicationAction.due_at <= now,
                    ),
                )
            )
            stmt = stmt.where(JobApplication.id.in_(due_ids))
        stmt = stmt.order_by(JobApplication.created_at.desc()).limit(limit).offset(offset)
        return list(self._s.execute(stmt).scalars().all())

    def update_fields(
        self, application_id: str, workspace_id: str, **fields
    ) -> Optional[JobApplication]:
        # status changes go through transition_status (state-machine checked);
        # id/workspace_id/job_id are immutable.
        allowed = {
            "profile_id", "lane", "excitement", "channel", "applied_at",
            "resume_run_id", "contact_name", "contact_note", "notes",
            "closed_reason",
        }
        row = self.get(application_id, workspace_id)
        if row is None:
            return None
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"field not updatable: {key}")
            setattr(row, key, value)
        self._s.flush()
        return row

    def delete_planned(self, application_id: str, workspace_id: str) -> bool:
        """Remove an application that was never applied to, with its rows.

        Scoped to `planned` on purpose. A mis-add is always a fresh row — wrong
        URL, duplicate, something typed to try the box — so this line covers
        every mistake worth erasing. Past that point the record is history: the
        funnel, the interview rate and the frozen weekly snapshots are all
        counted from it, and deleting one would move numbers the user reads to
        judge how the search is going, silently and with nothing left to point
        at. Those close out (`rejected` / `withdrawn` / `ghosted`) instead.

        Children go first and explicitly: application_events.application_id is
        NOT NULL with no ON DELETE, and neither relationship declares a cascade,
        so the FK would reject the delete (postgres) or orphan the rows
        (sqlite). Returns False when there is nothing to delete or the status
        does not allow it, so the route can tell 404 from 409.
        """
        from sqlalchemy import delete as sa_delete

        row = self.get(application_id, workspace_id)
        if row is None or row.status != "planned":
            return False
        self._s.execute(
            sa_delete(ApplicationEvent).where(
                ApplicationEvent.application_id == row.id,
                ApplicationEvent.workspace_id == workspace_id,
            )
        )
        self._s.execute(
            sa_delete(ApplicationAction).where(
                ApplicationAction.application_id == row.id,
                ApplicationAction.workspace_id == workspace_id,
            )
        )
        self._s.delete(row)
        self._s.flush()
        return True

    def transition_status(
        self,
        application_id: str,
        workspace_id: str,
        new_status: str,
        *,
        note: str | None = None,
        force: bool = False,
    ) -> Optional[JobApplication]:
        from packages.domain.applications.transitions import CLOSED_STATUSES, assert_transition

        row = self.get(application_id, workspace_id)
        if row is None:
            return None
        old_status = row.status
        assert_transition(old_status, new_status, force=force)  # raises InvalidTransition
        row.status = new_status
        # Stamp applied_at the first time we reach "applied" (mirrors
        # TaskRepository.mark_running stamping started_at).
        if new_status == "applied" and row.applied_at is None:
            row.applied_at = datetime.now(timezone.utc)
        # Closing the application retires its outstanding to-dos in the same
        # transaction; the count rides along in the audit event so the timeline
        # can say how much work the close took off the list.
        cancelled = (
            self._cancel_pending_actions(row.id, workspace_id)
            if new_status in CLOSED_STATUSES
            else 0
        )
        # Same-transaction audit event (append-only timeline).
        self._s.add(
            ApplicationEvent(
                application_id=row.id,
                workspace_id=workspace_id,
                event_type="status_changed",
                message=note,
                payload_json={
                    "from": old_status,
                    "to": new_status,
                    "forced": force,
                    "cancelled_actions": cancelled,
                },
            )
        )
        self._s.flush()
        return row

    def _cancel_pending_actions(self, application_id: str, workspace_id: str) -> int:
        """Retire this application's outstanding to-dos. Returns how many.

        Nothing else does. The rules engine only ever creates rows
        (planner_run.run_daily_rules_once never prunes) and `list_due` filters
        on (workspace, status, due_at) without joining the application — so a
        follow-up raised the day before a rejection keeps surfacing on Today
        for a company that is no longer in play, indefinitely.

        The retired status is RETIRED_STATUS ("cancelled"), NOT "dismissed".
        `_suppressed()` treats *dismissed* as a lifetime veto per
        (application, type), so reusing it here would leave a force-reopened
        application permanently silent — the correction path would quietly
        break the engine for that row. The constant is imported from the rules
        module rather than spelled here so the two sides cannot drift; the
        invariant that ties them is asserted in test_planner_rules.py.
        """
        from sqlalchemy import select

        from packages.domain.planner.rules import RETIRED_STATUS

        stmt = select(ApplicationAction).where(
            ApplicationAction.application_id == application_id,
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.status == "pending",
        )
        rows = list(self._s.scalars(stmt))
        for action in rows:
            action.status = RETIRED_STATUS
        return len(rows)

    def count_by_status(self, workspace_id: str) -> dict[str, int]:
        from sqlalchemy import func, select

        stmt = (
            select(JobApplication.status, func.count())
            .where(JobApplication.workspace_id == workspace_id)
            .group_by(JobApplication.status)
        )
        return {status: count for status, count in self._s.execute(stmt).all()}

    def list_job_ids_for_workspace(self, workspace_id: str) -> set[str]:
        """Job ids this workspace already has an application for — used to mark
        the jobs library with an "applied" flag so the user doesn't re-apply.
        Mirrors JobFavoriteRepository.list_job_ids_for_workspace."""
        from sqlalchemy import select

        stmt = select(JobApplication.job_id).where(
            JobApplication.workspace_id == workspace_id
        )
        return set(self._s.execute(stmt).scalars().all())

    def list_workspace_ids_with_applications(self) -> list[str]:
        """Distinct workspace ids that have at least one application — the daily
        planner beat iterates these (skips workspaces with an empty tracker)."""
        from sqlalchemy import select

        stmt = select(JobApplication.workspace_id).distinct()
        return list(self._s.execute(stmt).scalars().all())

    def count_applied_in_range(
        self, workspace_id: str, start_utc: datetime, end_utc: datetime
    ) -> int:
        """Applications whose applied_at falls in [start, end) — this-week triplet."""
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(JobApplication)
            .where(
                JobApplication.workspace_id == workspace_id,
                JobApplication.applied_at >= start_utc,
                JobApplication.applied_at < end_utc,
            )
        )
        return int(self._s.execute(stmt).scalar_one())


class ApplicationEventRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def append(
        self,
        *,
        application_id: str,
        workspace_id: str,
        event_type: str,
        message: str | None = None,
        payload_json: dict | None = None,
    ) -> ApplicationEvent:
        event = ApplicationEvent(
            application_id=application_id,
            workspace_id=workspace_id,
            event_type=event_type,
            message=message,
            payload_json=payload_json,
        )
        self._s.add(event)
        self._s.flush()
        return event

    def list_for_application(
        self, application_id: str, workspace_id: str, limit: int = 200
    ) -> list[ApplicationEvent]:
        from sqlalchemy import select

        stmt = (
            select(ApplicationEvent)
            .where(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.workspace_id == workspace_id,
            )
            .order_by(ApplicationEvent.created_at)
            .limit(limit)
        )
        return list(self._s.execute(stmt).scalars().all())

    def list_by_type_for_workspace(
        self, workspace_id: str, event_type: str, limit: int = 20_000
    ) -> list[ApplicationEvent]:
        """All events of one kind across the workspace.

        Callers filter by time in Python because the timestamp that matters for
        an interview lives in payload_json (`at` — when the round happens), not
        in created_at (when it was logged), and JSON predicates are not portable
        between Postgres and the SQLite used by tests.

        The caller therefore needs the COMPLETE set, which is why the limit is
        set far above any real workspace rather than at a page size: `at` and
        `created_at` are uncorrelated — an interview booked months ahead is an
        old row pointing at a future date — so truncating by insertion recency
        would silently drop exactly the rows a date filter is looking for. One
        person's interview history does not approach 20k; a workspace that does
        has outgrown reading events this way, and should get a real index on the
        scheduled time."""
        from sqlalchemy import select

        stmt = (
            select(ApplicationEvent)
            .where(
                ApplicationEvent.workspace_id == workspace_id,
                ApplicationEvent.event_type == event_type,
            )
            .order_by(ApplicationEvent.created_at.desc())
            .limit(limit)
        )
        return list(self._s.execute(stmt).scalars().all())


class ApplicationActionRepository:
    """The planner's to-do table. `list_due` powers the Today view; the P1
    rules engine writes auto_generated rows into it."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        *,
        workspace_id: str,
        type: str,
        title: str,
        application_id: str | None = None,
        due_at: datetime | None = None,
        status: str = "pending",
        auto_generated: bool = False,
        payload_json: dict | None = None,
        est_minutes: int | None = None,
    ) -> ApplicationAction:
        row = ApplicationAction(
            workspace_id=workspace_id,
            application_id=application_id,
            type=type,
            title=title,
            due_at=due_at,
            status=status,
            auto_generated=auto_generated,
            payload_json=payload_json,
            est_minutes=est_minutes,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, action_id: str, workspace_id: str) -> Optional[ApplicationAction]:
        from sqlalchemy import select

        stmt = select(ApplicationAction).where(
            ApplicationAction.id == action_id,
            ApplicationAction.workspace_id == workspace_id,
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def list_due(
        self,
        workspace_id: str,
        on_or_before: datetime,
        *,
        include_undated: bool = True,
    ) -> list[ApplicationAction]:
        """Pending actions due on/before the given instant, soonest-due first.
        Undated pending actions are included by default (they read as "anytime"
        to-dos that should still surface in Today) and sort last."""
        from sqlalchemy import or_, select

        conditions = [ApplicationAction.due_at <= on_or_before]
        if include_undated:
            conditions.append(ApplicationAction.due_at.is_(None))
        stmt = (
            select(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.status == "pending",
                or_(*conditions),
            )
            .order_by(ApplicationAction.due_at.is_(None), ApplicationAction.due_at)
        )
        return list(self._s.execute(stmt).scalars().all())

    def list_for_application(
        self, application_id: str, workspace_id: str
    ) -> list[ApplicationAction]:
        from sqlalchemy import select

        stmt = (
            select(ApplicationAction)
            .where(
                ApplicationAction.application_id == application_id,
                ApplicationAction.workspace_id == workspace_id,
            )
            .order_by(ApplicationAction.due_at)
        )
        return list(self._s.execute(stmt).scalars().all())

    def list_due_between(
        self, workspace_id: str, start: datetime, end: datetime
    ) -> list[ApplicationAction]:
        """Pending to-dos whose due date falls in [start, end). Undated ones are
        excluded — they belong to no particular day, so they cannot weigh on one
        in the week strip."""
        from sqlalchemy import select

        stmt = select(ApplicationAction).where(
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.status == "pending",
            ApplicationAction.due_at.is_not(None),
            ApplicationAction.due_at >= start,
            ApplicationAction.due_at < end,
        )
        return list(self._s.execute(stmt).scalars().all())

    def list_pending_carried_into_today(
        self, workspace_id: str, today_start: datetime
    ) -> list[tuple[str, Optional[int]]]:
        """Pending to-dos that weigh on today without being due today: those
        whose due date has already passed, plus undated ones.

        The week strip needs this so today's cell agrees with the capacity bar
        directly beneath it — that bar counts overdue and undated work as today's
        load (they are what you actually owe today), and a strip showing zero
        against a bar showing three is a self-contradiction on one screen.
        `today_start` is exclusive, so work due today is not double-counted with
        the week-range query.

        Returns one row per to-do rather than a count, because the strip needs
        both how MANY and how LONG. Two queries could answer that separately and
        would be free to drift apart the first time one grew a condition the
        other did not; one row set cannot. Only the two columns the caller reads
        are selected — hydrating whole ORM objects to discard them would make a
        large backlog expensive on every Plan load."""
        from sqlalchemy import or_, select

        stmt = select(ApplicationAction.type, ApplicationAction.est_minutes).where(
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.status == "pending",
            or_(
                ApplicationAction.due_at < today_start,
                ApplicationAction.due_at.is_(None),
            ),
        )
        return list(self._s.execute(stmt).all())

    def list_global_for_workspace(self, workspace_id: str) -> list[ApplicationAction]:
        """Workspace-global actions (application_id IS NULL) in any status — the
        rules engine reads these to dedup queue_refill per week."""
        from sqlalchemy import select

        stmt = select(ApplicationAction).where(
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.application_id.is_(None),
        )
        return list(self._s.execute(stmt).scalars().all())

    def count_completed_by_type_in_range(
        self, workspace_id: str, type_: str, start_utc: datetime, end_utc: datetime
    ) -> int:
        """Completed actions of a type whose completed_at falls in [start, end) —
        this-week triplet (outreach = networking done, follow_ups = follow_up done)."""
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.type == type_,
                ApplicationAction.status == "done",
                ApplicationAction.completed_at >= start_utc,
                ApplicationAction.completed_at < end_utc,
            )
        )
        return int(self._s.execute(stmt).scalar_one())

    def sum_est_for_ids(self, workspace_id: str, action_ids: list[str]) -> int:
        """Total effective estimate of these to-dos, workspace-scoped.

        Ids that don't exist, or belong to someone else, contribute nothing and
        raise nothing: the caller is snapshotting what the user kept, and a
        stale id from a list that moved under them should not fail the ritual.
        Nothing reports how many were counted — the wizard closes on submit, so
        there is nowhere to show it. That makes this the wrong call to learn
        from whether an id exists.
        """
        if not action_ids:
            return 0
        from sqlalchemy import select

        from packages.domain.planner.rules import effective_est_minutes

        stmt = select(ApplicationAction).where(
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.id.in_(action_ids),
        )
        rows = self._s.execute(stmt).scalars().all()
        return sum(effective_est_minutes(r.type, r.est_minutes) for r in rows)

    def count_completed_in_range(
        self, workspace_id: str, start_utc: datetime, end_utc: datetime
    ) -> int:
        """How many to-dos were completed in [start, end) — the done bar's
        count, of any type (unlike count_completed_by_type_in_range, which the
        weekly triplet uses)."""
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.status == "done",
                ApplicationAction.completed_at >= start_utc,
                ApplicationAction.completed_at < end_utc,
            )
        )
        return int(self._s.execute(stmt).scalar_one())

    def sum_est_completed_in_range(
        self, workspace_id: str, start_utc: datetime, end_utc: datetime
    ) -> int:
        """Total effective estimate of everything completed in [start, end).

        Summed in python rather than SQL because the per-type fallback for a
        NULL est_minutes lives in the domain layer — a COALESCE here would be a
        second copy of that table, free to drift from the one the user's
        capacity bar was drawn with."""
        from sqlalchemy import select

        from packages.domain.planner.rules import effective_est_minutes

        stmt = select(ApplicationAction).where(
            ApplicationAction.workspace_id == workspace_id,
            ApplicationAction.status == "done",
            ApplicationAction.completed_at >= start_utc,
            ApplicationAction.completed_at < end_utc,
        )
        rows = self._s.execute(stmt).scalars().all()
        return sum(effective_est_minutes(r.type, r.est_minutes) for r in rows)

    def complete(self, action_id: str, workspace_id: str) -> Optional[ApplicationAction]:
        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        # Idempotent. Two tabs, or a retried PATCH, used to move completed_at and
        # append a SECOND action_completed event — which then outlived a reopen,
        # because that deletes the completion it undoes, not every one ever
        # written for the row.
        if row.status == "done":
            return row
        row.status = "done"
        row.completed_at = datetime.now(timezone.utc)
        # Completing an action worth a timeline entry on its application.
        if row.application_id:
            self._s.add(
                ApplicationEvent(
                    application_id=row.application_id,
                    workspace_id=workspace_id,
                    event_type="action_completed",
                    message=row.title,
                    payload_json={"action_id": row.id, "type": row.type},
                )
            )
        self._s.flush()
        return row

    def reopen(self, action_id: str, workspace_id: str) -> Optional[ApplicationAction]:
        """Undo a completion — back to pending, exactly as it was.

        Deliberately not expressible as a snooze, which is the shape it first
        looks like: snooze() cannot restore an UNDATED to-do (there is no way to
        write due_at back to NULL), it would count the restoration as a
        postponement for that row (was_due is None -> snooze_count += 1), and it
        leaves completed_at pointing at a completion that no longer happened.

        The `action_completed` event goes with it, and this is the one place
        where the append-only convention argues FOR removal. That event is not a
        record of something that happened and was later reversed — it is the
        record of a mis-click the user retracted the same day. Leaving it would
        also leave `_check_in` (rules.py) and the check-in alert (funnel.py)
        measuring staleness from it, so the nudge the user just restored would
        stay suppressed for days by the click they undid.

        Idempotent: reopening a row that is not done changes nothing.
        """
        from sqlalchemy import select

        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        if row.status != "done":
            return row
        row.status = "pending"
        row.completed_at = None
        if row.application_id:
            stmt = (
                select(ApplicationEvent)
                .where(
                    ApplicationEvent.application_id == row.application_id,
                    ApplicationEvent.workspace_id == workspace_id,
                    ApplicationEvent.event_type == "action_completed",
                )
                .order_by(ApplicationEvent.created_at.desc())
            )
            # payload_json is filtered here rather than in SQL: JSON predicates
            # differ across backends and this list is one application's events.
            # Every one of them, not the newest: complete() is idempotent now,
            # but rows completed twice before that fix still carry duplicates,
            # and leaving one behind is the same lie in a quieter font.
            for event in self._s.execute(stmt).scalars():
                if (event.payload_json or {}).get("action_id") == row.id:
                    self._s.delete(event)
        self._s.flush()
        return row

    def snooze(
        self,
        action_id: str,
        workspace_id: str,
        days: int = 1,
        *,
        until: Optional[datetime] = None,
    ) -> Optional[ApplicationAction]:
        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        was_due = row.due_at
        if until is not None:
            # Absolute target (Rest-until-Monday) — correct for overdue actions,
            # whose due_at is in the past and would otherwise stay past on +days.
            row.due_at = until
        else:
            base = row.due_at or datetime.now(timezone.utc)
            row.due_at = base + timedelta(days=days)
        row.status = "pending"  # stays actionable, just later
        # Count only actual postponement. Rest-until-Monday applies one absolute
        # target to every visible action, which pulls anything due later than
        # that Monday EARLIER — counting those would inflate the number on rows
        # that were never put off, and two taps would light up "deferred" across
        # the whole list. Undated work does count: giving it tomorrow's date is
        # a postponement of something that was available today.
        # (SQLite round-trips drop tzinfo, so normalise before comparing.)
        def _aware(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

        if was_due is None or _aware(row.due_at) > _aware(was_due):
            row.snooze_count = (row.snooze_count or 0) + 1
        self._s.flush()
        return row

    def dismiss(self, action_id: str, workspace_id: str) -> Optional[ApplicationAction]:
        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        row.status = "dismissed"
        self._s.flush()
        return row

    def schedule(
        self, action_id: str, workspace_id: str, at: datetime
    ) -> Optional[ApplicationAction]:
        """Place a to-do at a time of day, or move one already placed.

        Deliberately not expressed through snooze(), which is the shape it first
        resembles. Scheduling records where on the calendar the user intends to
        sit down and do the thing; due_at records which day it is owed. They are
        independent: a to-do due Friday can be scheduled for Wednesday without
        anything being postponed. Routing this through snooze() would move due_at
        and bump snooze_count, reporting a deferral that never happened — the
        same confusion V5-C7 and V2-C5 each had to unpick once already.
        """
        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        row.scheduled_at = at
        self._s.flush()
        return row

    def unschedule(self, action_id: str, workspace_id: str) -> Optional[ApplicationAction]:
        """Return a to-do to the tray.

        due_at is deliberately untouched: the work is still owed on the same day,
        it just no longer has a place on the calendar. Clearing both would turn
        "I'll find another time for this" into "this isn't due any more".
        """
        row = self.get(action_id, workspace_id)
        if row is None:
            return None
        row.scheduled_at = None
        self._s.flush()
        return row

    def list_scheduled_between(
        self, workspace_id: str, start: datetime, end: datetime
    ) -> list[ApplicationAction]:
        """To-dos placed on the calendar within [start, end), earliest first.

        Unlike list_due_between this is not restricted to pending rows: a block
        the user finished is still a true record of how that day was spent, and
        dropping it the moment it is ticked would make the day look emptier the
        more got done. Retired rows are excluded — a cancelled to-do belongs to
        an application that closed, so its block is no longer anyone's plan.
        """
        from sqlalchemy import select

        from packages.domain.planner.rules import RETIRED_STATUS

        stmt = (
            select(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.status.not_in(("dismissed", RETIRED_STATUS)),
                ApplicationAction.scheduled_at.is_not(None),
                ApplicationAction.scheduled_at >= start,
                ApplicationAction.scheduled_at < end,
            )
            .order_by(ApplicationAction.scheduled_at, ApplicationAction.id)
        )
        return list(self._s.execute(stmt).scalars().all())

    def list_unscheduled(self, workspace_id: str) -> list[ApplicationAction]:
        """The tray: pending to-dos with no place on the calendar yet.

        Ordered by due date so the most pressing work is nearest the top of the
        tray; undated ones sort last, as they do in Today.
        """
        from sqlalchemy import select

        stmt = (
            select(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.status == "pending",
                ApplicationAction.scheduled_at.is_(None),
            )
            .order_by(
                ApplicationAction.due_at.is_(None),
                ApplicationAction.due_at,
                ApplicationAction.id,
            )
        )
        return list(self._s.execute(stmt).scalars().all())

    def count_due(self, workspace_id: str, on_or_before: datetime) -> int:
        from sqlalchemy import func, or_, select

        stmt = (
            select(func.count())
            .select_from(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.status == "pending",
                or_(
                    ApplicationAction.due_at.is_(None),
                    ApplicationAction.due_at <= on_or_before,
                ),
            )
        )
        return int(self._s.execute(stmt).scalar_one())

    def earliest_pending_action_map(
        self, workspace_id: str, application_ids: list[str]
    ) -> dict[str, tuple[datetime, str]]:
        """Per application, the soonest pending dated action as (due_at, type).
        Powers the list row's next-action column (due date + semantic type, e.g.
        "follow-up due") in one query (avoids per-row N+1).

        Ties break on id. Due dates are local midnights, so two to-dos falling on
        the same day is ordinary (a follow-up and a thank-you both landing
        Tuesday), and with due_at alone the winner was whatever the database
        happened to return first. The row's "Reschedule" action re-derives this
        same choice client-side to move the to-do the row is showing — an
        undefined tie makes that a coin flip between the shown one and another.
        """
        if not application_ids:
            return {}
        from sqlalchemy import select

        stmt = (
            select(ApplicationAction)
            .where(
                ApplicationAction.workspace_id == workspace_id,
                ApplicationAction.application_id.in_(application_ids),
                ApplicationAction.status == "pending",
                ApplicationAction.due_at.is_not(None),
            )
            .order_by(ApplicationAction.due_at, ApplicationAction.id)
        )
        result: dict[str, tuple[datetime, str]] = {}
        for a in self._s.execute(stmt).scalars().all():
            # ordered by (due_at, id) → first seen per app is the earliest.
            if a.application_id not in result:
                result[a.application_id] = (a.due_at, a.type)
        return result


class PlannerDayLogRepository:
    """One row per (workspace, local day) — the morning commitment and the
    evening close. flush-never-commit, like every repository here."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get_for_date(self, workspace_id: str, local_date: date) -> Optional[PlannerDayLog]:
        from sqlalchemy import select

        stmt = select(PlannerDayLog).where(
            PlannerDayLog.workspace_id == workspace_id,
            PlannerDayLog.local_date == local_date,
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def list_for_range(
        self, workspace_id: str, start: date, end: date
    ) -> list[PlannerDayLog]:
        """Day logs with local_date in [start, end) — the weekly review's
        per-day comparison. Ordered so the caller can zip it against a week."""
        from sqlalchemy import select

        stmt = (
            select(PlannerDayLog)
            .where(
                PlannerDayLog.workspace_id == workspace_id,
                PlannerDayLog.local_date >= start,
                PlannerDayLog.local_date < end,
            )
            .order_by(PlannerDayLog.local_date)
        )
        return list(self._s.execute(stmt).scalars().all())

    def commit_day(
        self, workspace_id: str, local_date: date, *, committed_est: int
    ) -> PlannerDayLog:
        """Record the morning commitment, creating the day's row if needed.

        Re-running the ritual overwrites: the latest commitment is the one the
        user is working against, and a stale first answer would make the evening
        comparison measure a plan they had already replaced."""
        row = self.get_for_date(workspace_id, local_date)
        if row is None:
            row = PlannerDayLog(
                workspace_id=workspace_id,
                local_date=local_date,
                committed_est=committed_est,
            )
            self._s.add(row)
        else:
            row.committed_est = committed_est
        self._s.flush()
        return row

    def close_day(
        self,
        workspace_id: str,
        local_date: date,
        *,
        done_est: int,
        reflection: Optional[str],
        now_utc: datetime,
    ) -> PlannerDayLog:
        """Record the evening close. Creates the row if the morning ritual was
        skipped — closing a day you never planned is a real thing to do, and it
        leaves committed_est NULL, which is exactly what happened.

        done_est is refreshed every time (it is a measurement, and reopening the
        laptop after closing changes it) while closed_at keeps the FIRST close —
        when you declared the day over, like read_at on a review. A blank
        reflection does not erase one already written."""
        row = self.get_for_date(workspace_id, local_date)
        if row is None:
            row = PlannerDayLog(workspace_id=workspace_id, local_date=local_date)
            self._s.add(row)
        row.done_est = done_est
        if reflection:
            row.reflection = reflection
        if row.closed_at is None:
            row.closed_at = now_utc
        self._s.flush()
        return row


class PlannerReviewRepository:
    """The weekly review table (one row per workspace+ISO-week). The weekly beat
    upserts; the Plan view's Review zone reads the latest. flush-never-commit."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get_for_week(self, workspace_id: str, week_start: date) -> Optional[PlannerReview]:
        from sqlalchemy import select

        stmt = select(PlannerReview).where(
            PlannerReview.workspace_id == workspace_id,
            PlannerReview.week_start == week_start,
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def get_latest(self, workspace_id: str) -> Optional[PlannerReview]:
        from sqlalchemy import select

        stmt = (
            select(PlannerReview)
            .where(PlannerReview.workspace_id == workspace_id)
            .order_by(PlannerReview.week_start.desc())
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def upsert(
        self,
        *,
        workspace_id: str,
        week_start: date,
        stats_json: dict,
        narrative_md: str | None,
    ) -> PlannerReview:
        """Insert or replace the review for (workspace, week). Idempotent so the
        weekly beat can re-run (or a regeneration) without duplicating rows.

        Re-announcing is driven by the STATS, not the prose. The narrative comes
        from a model with no temperature or seed pinned, so its text differs on
        every regeneration — comparing it would clear read_at on literally every
        re-run and train the user to swat the banner. The stats are the review;
        the narrative is prose about them.

        The one narrative change that IS new information: a degraded review
        gaining prose on a retry. The user read a numbers-only card and the
        summary arrived afterwards, so keeping it "read" would bury exactly what
        the retry produced. Prose going the other way (a re-run that degrades)
        does not re-nag — nothing new was said."""
        row = self.get_for_week(workspace_id, week_start)
        if row is None:
            row = PlannerReview(
                workspace_id=workspace_id,
                week_start=week_start,
                stats_json=stats_json,
                narrative_md=narrative_md,
            )
            self._s.add(row)
        else:
            narrative_arrived = row.narrative_md is None and narrative_md is not None
            if row.stats_json != stats_json or narrative_arrived:
                row.read_at = None
            row.stats_json = stats_json
            row.narrative_md = narrative_md
        self._s.flush()
        return row

    def mark_read(
        self, workspace_id: str, week_start: date, *, now_utc: datetime
    ) -> Optional[PlannerReview]:
        """Stamp when the user first opened this week's review; None if there is
        no such review for this workspace (the route turns that into a 404, which
        is also the IDOR answer for another workspace's week).

        A second call keeps the original timestamp — "when did you first see it"
        is the fact worth having, and it makes the endpoint idempotent under the
        double-click the banner's button invites."""
        row = self.get_for_week(workspace_id, week_start)
        if row is None:
            return None
        if row.read_at is None:
            row.read_at = now_utc
            self._s.flush()
        return row
