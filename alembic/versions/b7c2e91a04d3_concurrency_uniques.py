"""concurrency uniques: members, oidc/saml, devices, jobs(status, created_at).

Revision ID: b7c2e91a04d3
Revises: c478c5acf8f4
Create Date: 2026-08-14

Empty DBs: alembic upgrade head. Legacy DBs: migrate_schema.apply_concurrency_indexes.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "b7c2e91a04d3"
down_revision: Union[str, None] = "c478c5acf8f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from autopilot_platform.platform.core.db import apply_concurrency_indexes

    apply_concurrency_indexes(op.get_bind())


def downgrade() -> None:
    for name in (
        "ix_jobs_status_created_at",
        "uq_users_saml_nameid",
        "uq_users_oidc_sub",
        "uq_device_runner_udid",
        "uq_project_member_user",
        "uq_org_member_user",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
