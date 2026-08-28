"""widen jobs/schedules.backend_mode for HTTP api_env profiles.

Revision ID: e4f8a1c209b7
Revises: b7c2e91a04d3
Create Date: 2026-08-17

SQLite 不强制 VARCHAR 长度，升级为 no-op。PostgreSQL 扩到 64。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from autopilot_platform.core.job_platforms import BACKEND_MODE_MAX_LEN


revision: str = "e4f8a1c209b7"
down_revision: Union[str, None] = "b7c2e91a04d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in ("jobs", "schedules"):
        op.alter_column(
            table,
            "backend_mode",
            existing_type=sa.String(length=32),
            type_=sa.String(length=BACKEND_MODE_MAX_LEN),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in ("jobs", "schedules"):
        op.alter_column(
            table,
            "backend_mode",
            existing_type=sa.String(length=BACKEND_MODE_MAX_LEN),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
