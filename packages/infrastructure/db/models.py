"""
SQLAlchemy ORM models.

Tables:
  Auth:   users, workspace_members
  Core:   workspaces, runs, tasks, task_events, artifacts
  Agent:  agent_invocations, agent_tool_events, agent_validation_results

Rules (enforced here and in AGENTS.md):
  - OpenClaw never writes to these tables directly
  - agent_invocations.session_key is platform-generated, never from frontend
  - Validator Gate must pass before writing to jobs-style tables
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Auth tables
# ---------------------------------------------------------------------------


class User(Base):
    """Platform user — provider-agnostic identity anchor.

    Auth provider details (e.g. Clerk user id) live in UserIdentity,
    not here. This table is the source of truth for all business data.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workspace_memberships: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="user"
    )


class UserIdentity(Base):
    """External auth provider identity linked to a local User.

    One row per (user, provider) pair. Allows a user to authenticate
    via multiple providers (Clerk, GitHub, Google, enterprise SSO) or
    migrate between providers without touching business tables.

    provider examples: "clerk", "github", "google", "password"
    provider_user_id: the external id (e.g. Clerk JWT sub claim).
    """

    __tablename__ = "user_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="identities")


class WorkspaceMember(Base):
    """Membership record linking a user to a workspace with a role."""

    __tablename__ = "workspace_members"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="workspace_memberships")
    workspace: Mapped["Workspace"] = relationship(back_populates="members")


# ---------------------------------------------------------------------------
# Core tables
# ---------------------------------------------------------------------------


class Workspace(Base):
    """Logical isolation unit. MVP: one workspace per user."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    runs: Mapped[list["Run"]] = relationship(back_populates="workspace")
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace")


class Run(Base):
    """
    Top-level unit of work initiated by the user.
    run_type determines which task types get created.
    input_snapshot_json captures the user's inputs at creation time (immutable).
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    run_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", index=True
    )
    input_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="runs")
    tasks: Mapped[list["Task"]] = relationship(back_populates="run")
    task_events: Mapped[list["TaskEvent"]] = relationship(back_populates="run")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run")
    agent_invocations: Mapped[list["AgentInvocation"]] = relationship(back_populates="run")


class Task(Base):
    """
    A single unit of async execution within a run.
    Status machine: queued → running → succeeded | failed | cancelled | needs_review
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    run: Mapped["Run"] = relationship(back_populates="tasks")
    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="task")
    agent_invocations: Mapped[list["AgentInvocation"]] = relationship(back_populates="task")


class TaskEvent(Base):
    """Append-only log of task lifecycle steps. UI reads this for progress display."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    task: Mapped["Task"] = relationship(back_populates="events")
    run: Mapped["Run"] = relationship(back_populates="task_events")


class Artifact(Base):
    """
    Pointer to a file on the artifact storage (local volume or object store).
    Only written after Validator Gate passes.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["Run"] = relationship(back_populates="artifacts")
    task: Mapped["Task"] = relationship(back_populates="artifacts")


# ---------------------------------------------------------------------------
# Agent-specific tables (new in v2)
# ---------------------------------------------------------------------------


class AgentInvocation(Base):
    """
    One OpenClaw agent execution.
    Created by worker before calling agent_runtime.invoke().
    Updated by worker after result is received.
    """

    __tablename__ = "agent_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Platform-generated. Never comes from frontend. Format:
    # agent:<agent_id>:workspace:<ws_id>:run:<run_id>:task:<task_id>:attempt:<n>
    session_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    skill_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )
    input_spec_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_manifest_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdout_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["Run"] = relationship(back_populates="agent_invocations")
    task: Mapped["Task"] = relationship(back_populates="agent_invocations")
    tool_events: Mapped[list["AgentToolEvent"]] = relationship(back_populates="invocation")
    validation_results: Mapped[list["AgentValidationResult"]] = relationship(
        back_populates="invocation"
    )


class AgentToolEvent(Base):
    """
    One tool call made by the agent during an invocation.
    Written by agent tool wrappers (career_*.py) via the platform,
    NOT by OpenClaw directly.

    Signed-ledger fields (added in migration c3d4e5f6a7b8):
      event_id        — platform "tevt_<uuid4>" from ToolLedgerEvent
      sequence        — 1-based within invocation
      prev_event_hash — sha256 of previous event in chain
      event_hash      — sha256 of canonical event JSON
      signature       — HMAC-SHA256 of event_hash
      raw_event_json  — full ToolLedgerEvent dict for audit/replay
    """

    __tablename__ = "agent_tool_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    invocation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_invocations.id"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ok")
    # Signed-ledger fields
    event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True)
    sequence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prev_event_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_event_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    invocation: Mapped["AgentInvocation"] = relationship(back_populates="tool_events")


class AgentValidationResult(Base):
    """
    One validator's verdict on an agent's output manifest.
    If any validator status == "failed", the task moves to needs_review
    and no jobs/artifacts are written.
    """

    __tablename__ = "agent_validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    invocation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_invocations.id"), nullable=False, index=True
    )
    validator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # passed | failed | warning
    errors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    invocation: Mapped["AgentInvocation"] = relationship(back_populates="validation_results")


# ---------------------------------------------------------------------------
# LLM usage tracking
# ---------------------------------------------------------------------------


class LLMUsageEvent(Base):
    """Append-only ledger of LLM API calls with token counts and estimated cost.

    One row per LLMClient.complete() or complete_structured() call.
    Written by the usage_writer callback inside the worker process.
    """

    __tablename__ = "llm_usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=True, index=True
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True, index=True
    )
    workspace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    call_site: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Job tables
# ---------------------------------------------------------------------------


class Job(Base):
    """Canonical job record. Populated from discovery candidate_pool after validator gate."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    jd_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jd_hash: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("discovered", "reportable", "invalid", "stale", name="job_status"),
        nullable=False,
        default="discovered",
    )
    discovered_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    discovered_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JobReport(Base):
    """Global (user-independent) Job Intelligence Report for a specific job."""

    __tablename__ = "job_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    jd_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    used_research: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    research_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    research_bundle_hash: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    status: Mapped[str] = mapped_column(
        Enum("active", "superseded", "failed", name="job_report_status"),
        nullable=False,
        default="active",
    )
    narrative_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    structured_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    structured_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class FitReport(Base):
    """Workspace-private Candidate Fit Report for a job/profile pair."""

    __tablename__ = "fit_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    job_report_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_reports.id"), nullable=False)
    candidate_profile_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    profile_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "superseded", "failed", name="fit_report_status"),
        nullable=False,
        default="active",
    )
    structured_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    narrative_artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    structured_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateProfile(Base):
    """Workspace-private career profile — single source of truth for both Discovery and FitReport.

    One profile per workspace (MVP). Discovery reads narrative fields via ProfileSnapshot adapter.
    FitReport reads skills/domain/project fields directly from this table.
    """

    __tablename__ = "candidate_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # Narrative (Discovery + FitReport LLM both read summary)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    experience_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    education_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Skills & subject areas
    technical_skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    subject_areas: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tools: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Projects (FitReport evidence)
    representative_projects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Quantitative
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profile_hash: Mapped[str] = mapped_column(String(32), nullable=False, default="empty")
    structured_resume_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    search_defaults: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CompanySource(Base):
    """ATS board auto-discovered from agent runs, used for API sync."""

    __tablename__ = "company_sources"
    __table_args__ = (
        UniqueConstraint("ats_provider", "board_token", name="uq_company_sources_provider_token"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ats_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    board_token: Mapped[str] = mapped_column(String(255), nullable=False)
    board_api_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    board_careers_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="discovered")
    discovered_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    job_count_last_sync: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SearchStrategyStateRow(Base):
    """Workspace-level cross-run search strategy (one row per workspace, MVP)."""

    __tablename__ = "search_strategy_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, unique=True, index=True
    )
    profile_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_reflection_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    last_reflection_task_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
