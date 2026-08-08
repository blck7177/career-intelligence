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
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    __table_args__ = (
        # The lookup every sign-in performs (provider + external id).
        Index(
            "ix_user_identities_provider", "provider", "provider_user_id", unique=True
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    __table_args__ = (Index("ix_workspace_members_workspace_id", "workspace_id"),)

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
    # "new" | "pro" | "max" | "beta" — governs per-run_type monthly quotas and
    # allowed search_depth values. See configs/quotas.yaml and
    # packages/domain/quota/tiers.py.
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Per-workspace planner configuration (weekly targets, follow-up/ghost
    # thresholds, rest days, ...) as one JSON blob. Null = use code defaults;
    # the read layer merges this over the PlannerSettings defaults. UI to edit
    # it lands in P1 — P0 only reads defaults.
    planner_settings_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    runs: Mapped[list["Run"]] = relationship(back_populates="workspace")
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace")


# Agent-driven run types only — job_report / fit_report intentionally allow
# multiple concurrent runs per workspace (batch analyze). Keep in lockstep with
# migration x5y6z7a8b9c0, which created the index from the same list.
_AGENT_RUN_TYPES = ("job_discovery", "job_research", "run_reflection", "candidate_story_build")
_ACTIVE_AGENT_RUN_PREDICATE = (
    "status IN ('queued', 'running') AND run_type IN ("
    + ", ".join(f"'{rt}'" for rt in _AGENT_RUN_TYPES)
    + ")"
)


class Run(Base):
    """
    Top-level unit of work initiated by the user.
    run_type determines which task types get created.
    input_snapshot_json captures the user's inputs at creation time (immutable).
    """

    __tablename__ = "runs"
    __table_args__ = (
        # One active agent run per (workspace, run_type). Partial on both axes:
        # only queued/running rows conflict, and only the agent-driven types —
        # job_report / fit_report deliberately allow concurrent runs (batch
        # analyze). Mirrors migration x5y6z7a8b9c0's raw DDL exactly; declared
        # for sqlite too because the test schema is built here, and a predicate
        # that only applied to postgres would become a FULL unique index in the
        # tests and reject the second run of any type.
        Index(
            "uq_active_agent_run_per_workspace_type",
            "workspace_id",
            "run_type",
            unique=True,
            postgresql_where=text(_ACTIVE_AGENT_RUN_PREDICATE),
            sqlite_where=text(_ACTIVE_AGENT_RUN_PREDICATE),
        ),
    )

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
    # "sha256:<64 hex>" — 71 chars, not 64. The initial schema declared
    # VARCHAR(64) and nothing ever widened it, so a database built from the
    # migration chain rejects every value this field is given. The only reason
    # nothing broke is that the running database was created by create_all()
    # from this 128 and later stamped. Migration i7j8k9l0m1n2 widens the column
    # to match; do not narrow this without changing what the writer produces.
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
    __table_args__ = (
        # Partial on purpose: the ledger's event_id is unique when present, but
        # rows predating the signed ledger have none, and a plain unique index
        # would collapse all of those NULLs-as-duplicates on some backends.
        # Declared for BOTH dialects — the tests build the schema on sqlite, and
        # a postgresql_where alone would silently become a FULL unique index
        # there, breaking every fixture that writes more than one legacy row.
        Index(
            "ix_agent_tool_events_event_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
            sqlite_where=text("event_id IS NOT NULL"),
        ),
    )

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
    # JSONB in postgres (what the migration created), plain JSON everywhere
    # else — the tests build this schema on sqlite, which cannot render JSONB
    # at all. A bare JSONB here makes create_all() raise before any test runs.
    raw_event_json: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
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
    __table_args__ = (
        Index("ix_jobs_company", "company"),
        Index("ix_jobs_jd_hash", "jd_hash"),
        Index("ix_jobs_status", "status"),
    )

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
        # 'archived' is a legacy per-user workflow value (added to the DB enum
        # by migration r9s0t1u2v3w4 but never to this model, which made ORM
        # hydration of archived rows raise LookupError). It belongs in
        # workspace_jobs.user_status and will move there; listed here so
        # existing rows load. Postgres can't drop an enum value, so it remains.
        Enum(
            "discovered", "reportable", "invalid", "stale", "archived",
            name="job_status",
        ),
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
    # Employer's original posting date, captured from the ATS board API when it
    # exposes one (Greenhouse/Lever/Ashby). NULL when unknown — created_at is our
    # ingest time, not the posting date, so "posted Xd" falls back to "seen Xd".
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadUrl(Base):
    """A job-posting URL confirmed dead on arrival — HTTP 404/410, or a page
    that loads (200) but says the posting is closed. Recorded here instead of
    creating a zombie 'discovered' job row, and used as a negative cache so the
    same dead URL isn't re-fetched on every discovery run. url_hash is over the
    normalized URL (see url_normalize). Revival is left to a later liveness
    sweep; a 404 rarely comes back."""

    __tablename__ = "dead_urls"
    __table_args__ = (
        # A named UNIQUE CONSTRAINT, which is what the migration created.
        # `unique=True` on the column would render as a unique INDEX instead —
        # same effect in postgres, different object, and the difference is
        # exactly what kept alembic reporting drift here.
        UniqueConstraint("url_hash", name="uq_dead_urls_url_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    url_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)  # http_404 | http_410 | closed_posting
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    discovered_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobReport(Base):
    """Global (user-independent) Job Intelligence Report for a specific job."""

    __tablename__ = "job_reports"
    __table_args__ = (
        Index("ix_job_reports_jd_hash", "jd_hash"),
        Index("ix_job_reports_job_id", "job_id"),
        Index("ix_job_reports_status", "status"),
    )

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
    __table_args__ = (
        Index("ix_fit_reports_job_report_id", "job_report_id"),
        Index("ix_fit_reports_status", "status"),
        # The list query's lookup: latest fit per (workspace, job).
        Index("ix_fit_reports_workspace_job", "workspace_id", "job_id"),
    )

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


class JobFavorite(Base):
    """Workspace-private bookmark on a job. Mirrors the FitReport split: Job is
    global/shared, favorited-ness is per-workspace preference data."""

    __tablename__ = "job_favorites"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", name="uq_job_favorites_workspace_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobNotInterested(Base):
    """Workspace-private dismissal of a job. Structurally identical to
    JobFavorite — Favorite already carries the positive "interested" signal,
    so this only needs to exist for the negative one."""

    __tablename__ = "job_not_interested"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", name="uq_job_not_interested_workspace_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
        Index("ix_company_sources_status", "status"),
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
    __table_args__ = (
        # Both objects exist in the database: a named UNIQUE CONSTRAINT plus a
        # plain (non-unique) index. `unique=True, index=True` on the column
        # would have collapsed them into one unique index.
        UniqueConstraint("workspace_id", name="search_strategy_states_workspace_id_key"),
        Index("ix_search_strategy_states_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False
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


# ---------------------------------------------------------------------------
# Application Tracker — workspace-private application tracking + planner
# (migration c0d1e2f3g4h5). Keep columns/indexes in sync with that migration.
# ---------------------------------------------------------------------------


class JobApplication(Base):
    """One row per application the user is tracking (submitted or planned).

    Workspace-private, mirroring the JobFavorite split: a Job is global/shared,
    while an *application* to it is per-workspace intent data. Every application
    references a job row (job_id NOT NULL): the job is created either by URL
    import or from a pasted JD (synthetic manual:// canonical_url) — both via the
    shared manual_import ingest pipeline. There are no bare/off-platform rows.

    Status machine (planned -> applied -> in_review -> interviewing -> offer,
    plus rejected|withdrawn|ghosted from any live state) lives in
    packages/domain/applications/transitions.py. Interview *rounds* are
    application_events, not statuses. `ghosted` is a suggested terminal marker
    (proposed by the planner, confirmed by the user).
    """

    __tablename__ = "job_applications"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", name="uq_job_applications_workspace_job"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False, index=True
    )
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("candidate_profiles.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned", index=True)
    lane: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # a | b | c
    excitement: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-3 gut feel
    channel: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resume_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list["ApplicationEvent"]] = relationship(back_populates="application")
    actions: Mapped[list["ApplicationAction"]] = relationship(back_populates="application")


class ApplicationEvent(Base):
    """Append-only timeline for an application: status changes, follow-ups,
    interview scheduling, email matches (P2). Same shape as TaskEvent.
    workspace_id is denormalized (copied from the parent) so Today/summary
    queries need no join — matches the migration, which puts no FK on it.

    event_at is when the thing the event describes HAPPENS (an interview's
    start), as opposed to created_at (when it was logged) — the two are
    uncorrelated, since a round booked weeks ahead is an old row pointing at a
    future date. NULL for event kinds that have no such instant (notes, status
    changes). Interview rows keep a copy in payload_json["at"] for backward
    compatibility; the column is what range queries filter on."""

    __tablename__ = "application_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_applications.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "ix_application_events_ws_type_at", "workspace_id", "event_type", "event_at"
        ),
    )

    application: Mapped["JobApplication"] = relationship(back_populates="events")


class ApplicationAction(Base):
    """A planner to-do. The "Today" view is a query over this table. Most rows
    are auto-generated by the (P1) rules engine; users can add rows manually.
    application_id is nullable for global actions (e.g. "run a discovery to
    refill the queue")."""

    __tablename__ = "application_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    application_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("job_applications.id"), nullable=True, index=True
    )
    # apply | follow_up | networking | prep | thank_you | custom | global
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Effort estimate in minutes. The rules engine emits a per-type default;
    # NULL on legacy rows and on manual rows the user did not estimate, so every
    # consumer needs a fallback (never SUM() this column blindly).
    est_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # When this to-do is planned to START, as an instant. due_at says which day
    # it is owed; this says where on that day it sits. NULL is the unscheduled
    # tray, not a default time — the week view is built around that distinction.
    # Duration is not stored here: est_minutes already carries it, and a second
    # copy could disagree with the total the capacity bar shows.
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # How many times this to-do has been pushed to a later day. Unlike
    # est_minutes, 0 is a real value here (never deferred), not "unknown".
    snooze_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # pending | done | dismissed | cancelled. (A snooze moves due_at and leaves
    # the row pending — there is no "snoozed" status.) "dismissed" is the user
    # saying "not needed", and the rules engine reads it as a lifetime veto for
    # that (application, type); "cancelled" is the system retiring the row
    # because its application closed, and suppresses nothing.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    application: Mapped[Optional["JobApplication"]] = relationship(back_populates="actions")


class PlannerDayLog(Base):
    """One day's plan-versus-outcome, per (workspace, local day).

    Written by the two rituals: the morning one snapshots what the user agreed
    to (committed_est), the evening one records what actually got done
    (done_est, measured server-side from completed_at) plus an optional
    reflection. The weekly review reads the pair back as a per-day comparison.

    Both totals are nullable and mean different things when absent: no row at
    all = the ritual never ran that day; a row with committed_est set and
    done_est NULL = planned but never closed. Treating either as zero would
    turn "didn't run the ritual" into "committed to nothing", which reads as a
    bad day rather than an unrecorded one."""

    __tablename__ = "planner_day_logs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "local_date", name="uq_planner_day_logs_workspace_date"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    # The calendar day in settings.timezone — the planner's one day boundary.
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Sum of the effective estimates of the to-dos kept in the morning ritual.
    # A snapshot: the list moves all day, this number does not.
    committed_est: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Sum of the effective estimates completed during this local day, measured
    # at close time from completed_at — never supplied by the client.
    done_est: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reflection: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When the day was FIRST closed. Re-closing refreshes done_est but leaves
    # this alone: the ritual moment is the fact worth keeping.
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlannerReview(Base):
    """One weekly review per (workspace, ISO-week) — the planner's Review zone.

    Written by the weekly Celery beat (Sun night, per settings.timezone). Holds
    the deterministic aggregate (stats_json, a WeeklyReviewStats dump) plus an
    optional LLM narrative; narrative_md is NULL when generation degraded to the
    pure-number template. Re-running the beat upserts on (workspace_id,
    week_start) rather than inserting a duplicate."""

    __tablename__ = "planner_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "week_start", name="uq_planner_reviews_workspace_week"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    # Monday of the reviewed week, in the workspace's settings.timezone.
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    stats_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    narrative_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When the user first opened this review; NULL = unread, which is what the
    # Plan view's banner keys off. Never overwritten on a second read — "when did
    # you first see it" is the fact worth keeping.
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
