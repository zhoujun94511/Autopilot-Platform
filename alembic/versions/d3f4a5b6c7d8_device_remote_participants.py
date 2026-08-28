"""Add Phase 3 remote participants and viewer limit.

Revision ID: d3f4a5b6c7d8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f4a5b6c7d8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("device_remote_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("max_viewers", sa.Integer(), nullable=False, server_default="5")
        )
    op.create_table(
        "device_remote_participants",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column(
            "connection_id", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="joining"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["device_remote_sessions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_device_remote_participants_session_id",
        "device_remote_participants",
        ["session_id"],
    )
    op.create_index(
        "ix_device_remote_participants_user_id",
        "device_remote_participants",
        ["user_id"],
    )
    op.create_index(
        "ix_device_remote_participants_role",
        "device_remote_participants",
        ["role"],
    )
    op.create_index(
        "ix_device_remote_participants_status",
        "device_remote_participants",
        ["status"],
    )
    op.create_index(
        "ix_device_remote_participant_session_status",
        "device_remote_participants",
        ["session_id", "status"],
    )
    op.create_index(
        "uq_device_remote_participant_connection",
        "device_remote_participants",
        ["session_id", "connection_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("device_remote_participants")
    with op.batch_alter_table("device_remote_sessions") as batch_op:
        batch_op.drop_column("max_viewers")
