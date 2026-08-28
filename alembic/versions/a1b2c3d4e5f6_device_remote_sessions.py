"""Create device_remote_sessions for Platform Web remote control (C1).

Revision ID: a1b2c3d4e5f6
Revises: f8c1d4a27e90
Create Date: 2026-08-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f8c1d4a27e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_remote_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("runner_id", sa.String(length=128), nullable=False),
        sa.Column("udid", sa.String(length=256), server_default="", nullable=False),
        sa.Column("platform", sa.String(length=64), server_default="", nullable=False),
        sa.Column(
            "reservation_id", sa.String(length=64), server_default="", nullable=False
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column(
            "capabilities_json", sa.Text(), server_default="[]", nullable=False
        ),
        sa.Column(
            "error_message", sa.String(length=512), server_default="", nullable=False
        ),
        sa.Column("signaling_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_device_remote_sessions_device_id", "device_remote_sessions", ["device_id"]
    )
    op.create_index(
        "ix_device_remote_sessions_runner_id", "device_remote_sessions", ["runner_id"]
    )
    op.create_index(
        "ix_device_remote_sessions_user_id", "device_remote_sessions", ["user_id"]
    )
    op.create_index(
        "ix_device_remote_sessions_status", "device_remote_sessions", ["status"]
    )
    op.create_index(
        "ix_device_remote_sessions_expires_at",
        "device_remote_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("device_remote_sessions")
