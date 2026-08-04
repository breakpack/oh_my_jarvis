"""SQLAlchemy 2.0 declarative models for Phase 0/1 (SPEC.md §14).

Only the columns needed by current call sites are modeled; the remaining
tables listed in SPEC.md §14 (tasks, memories, documents, skills, ...) are
added in later phases as their features land.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column()
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column()
    content: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    summary: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Memory(Base):
    """User/project memory (SPEC.md §8).

    No embedding column yet — Phase 3 adds it alongside the document
    embedding pipeline. Until then, retrieval is text search (ILIKE) only.
    """

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str] = mapped_column()
    source: Mapped[str] = mapped_column()
    confidence: Mapped[float] = mapped_column(default=1.0, server_default="1.0")
    valid_from: Mapped[datetime | None] = mapped_column(default=None)
    valid_until: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column()
    source_type: Mapped[str] = mapped_column()
    source_path: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="ready", server_default="ready")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column()
    section: Mapped[str | None] = mapped_column(default=None)
    page: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), unique=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column()
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="open", server_default="open")
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Approval(Base):
    """Approval object for risky Tool/action execution (SPEC.md §12)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column()
    target: Mapped[str] = mapped_column()
    risk_level: Mapped[str] = mapped_column()
    arguments: Mapped[dict] = mapped_column(JSONB)
    arguments_hash: Mapped[str] = mapped_column()
    preview: Mapped[str] = mapped_column()
    expected_effects: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    rollback_available: Mapped[bool] = mapped_column(default=False, server_default="false")
    rollback_token: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Workspace(Base):
    """Sandboxed development workspace (SPEC.md §9)."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_path: Mapped[str] = mapped_column()
    workspace_dir: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class WorkspaceRun(Base):
    """A single command execution inside a Workspace (SPEC.md §9).

    No workspace_artifacts table yet — artifacts stay as files in the
    workspace directory until a later phase needs them queryable from the
    DB.
    """

    __tablename__ = "workspace_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    command: Mapped[list] = mapped_column(JSONB)
    exit_code: Mapped[int | None] = mapped_column(default=None)
    stdout: Mapped[str] = mapped_column()
    stderr: Mapped[str] = mapped_column()
    duration_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditEvent(Base):
    """Append-only audit log (SPEC.md §20.4).

    `payload` carries the itemized fields from §20.4 (request, workflow,
    skill, model, search source, tool arguments hash, approval, tool
    result, verification, error, rollback) as JSONB rather than one column
    per field, since the shape varies by event_type. Sensitive bodies and
    secrets must not be written into it.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    event_type: Mapped[str] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
