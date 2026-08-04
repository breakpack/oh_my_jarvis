"""add tasks and approvals tables

Revision ID: d2d132cb076b
Revises: a62e372948b7
Create Date: 2026-08-04 09:47:14.101838+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d2d132cb076b"
down_revision: str | None = "a62e372948b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    op.create_table(
        "approvals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("arguments_hash", sa.String(), nullable=False),
        sa.Column("preview", sa.String(), nullable=False),
        sa.Column("expected_effects", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("rollback_available", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("rollback_token", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_approvals_status", table_name="approvals")
    op.drop_index("ix_approvals_user_id", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
