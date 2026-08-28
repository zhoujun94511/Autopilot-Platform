"""Alembic env（AUD-2026-07 切流）。

``init_db()`` 经 ``platform.core.alembic_align`` 调用本环境：

- 空库：``upgrade head``
- 已有库：``create_all`` + ``migrate_schema`` 后 ``stamp`` / ``upgrade``

新表/列变更应新增 revision；``SCHEMA_ADDS`` 为兼容补列层（见 ADR）。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM 元数据：与 init_db 一致，须同时加载核心 + 设计域模型
from autopilot_platform.platform.core.db import Base  # noqa: E402
import autopilot_platform.platform.core.models  # noqa: E402,F401
import autopilot_platform.platform.design.design_models  # noqa: E402,F401

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("MC_DATABASE_URL", "").strip()
    if url:
        return url
    return config.get_main_option("sqlalchemy.url") or "sqlite:///./data/alembic_scratch.db"


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite ALTER 限制；baseline / 后续改表更稳
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
