"""Persist the time a job acquired its devices.

Revision ID: f0b8c7d6e5a4
Revises: e9a7b6c5d4f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


revision = "f0b8c7d6e5a4"
down_revision = "e9a7b6c5d4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        # Older startup code could add this column and leave the revision behind.
        columns = sa.inspect(op.get_bind()).get_columns("jobs")
        if any(column["name"] == "claimed_at" for column in columns):
            return
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("claimed_at")
