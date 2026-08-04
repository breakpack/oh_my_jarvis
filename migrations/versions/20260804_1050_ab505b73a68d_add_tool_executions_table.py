"""add tool_executions table

Revision ID: ab505b73a68d
Revises: 36f6b55830ef
Create Date: 2026-08-04 10:50:34.979040+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ab505b73a68d"
down_revision: str | None = "36f6b55830ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("workflow_thread_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("arguments_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column("result", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "workflow_thread_id",
            "tool_name",
            "arguments_hash",
            name="uq_tool_executions_thread_tool_arguments",
        ),
    )
    op.create_index(
        "ix_tool_executions_workflow_thread_id", "tool_executions", ["workflow_thread_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_executions_workflow_thread_id", table_name="tool_executions")
    op.drop_table("tool_executions")
