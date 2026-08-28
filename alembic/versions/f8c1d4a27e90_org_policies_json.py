"""Add organizations.policies_json for org-level permission switches.

Revision ID: f8c1d4a27e90
Revises: e4f8a1c209b7
Create Date: 2026-08-17

Default ``{}``: members cannot create projects or invite colleagues.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f8c1d4a27e90"
down_revision: Union[str, None] = "e4f8a1c209b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "policies_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("policies_json")
