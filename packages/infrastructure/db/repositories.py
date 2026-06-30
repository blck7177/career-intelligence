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
    CandidateProfile,
    CompanySource,
    FitReport,
    Job,
    JobFavorite,
    JobReport,
    LLMUsageEvent,
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
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        """List jobs, optionally filtered by run_ids, status, and/or an explicit job_id set
        (the latter used for favorites_only)."""
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
    ) -> JobReport:
        row = JobReport(
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
    ) -> FitReport:
        row = FitReport(
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
