"""Persist Runner device inventory and explicit selection policy.

Revision ID: e9a7b6c5d4f3
Revises: d3f4a5b6c7d8
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e9a7b6c5d4f3"
down_revision: Union[str, None] = "d3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runners") as batch_op:
        batch_op.add_column(
            sa.Column("device_inventory_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("device_selection_mode", sa.String(16), nullable=False, server_default="all")
        )
        batch_op.add_column(
            sa.Column(
                "selected_device_udids_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch_op.add_column(
            sa.Column("device_policy_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index(
            "ix_runners_device_selection_mode", ["device_selection_mode"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("runners") as batch_op:
        batch_op.drop_index("ix_runners_device_selection_mode")
        batch_op.drop_column("device_policy_revision")
        batch_op.drop_column("selected_device_udids_json")
        batch_op.drop_column("device_selection_mode")
        batch_op.drop_column("device_inventory_json")
