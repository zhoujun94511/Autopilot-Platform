"""AUD-2026-07 切流：Alembic 与 init_db 对齐。

策略（兼容现网 create_all 库）：

- **空库**（无业务表）：``alembic upgrade head``；失败则回退 create_all
- **已有库**：``create_all`` + ``migrate_schema``（SCHEMA_ADDS / 预订索引修复）后：
  - 无 ``alembic_version`` → ``stamp head``（勿对已有表重跑 baseline）
  - 已有版本表 → ``upgrade head``（应用后续 revision）

未安装 alembic 时仅走 create_all + migrate_schema（开发兜底；生产请装依赖）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, inspect

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
HEAD = "head"


def _is_sqlite_memory(db_url: str) -> bool:
    """``sqlite:///:memory:`` 每个连接是独立空库；Alembic 再开引擎会把表建到另一块内存。"""
    u = (db_url or "").strip().lower()
    if not u.startswith("sqlite"):
        return False
    return ":memory:" in u or u.rstrip("/") in ("sqlite://", "sqlite+pysqlite://")


def alembic_available() -> bool:
    if not ALEMBIC_INI.is_file():
        return False
    try:
        import alembic  # noqa: F401
    except ImportError:
        return False
    return True


def _config(db_url: str):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _with_db_url(db_url: str):
    """env.py 优先读 MC_DATABASE_URL；临时写入并在结束后恢复。"""

    class _Ctx:
        def __enter__(self):
            self._prev = os.environ.get("MC_DATABASE_URL")
            os.environ["MC_DATABASE_URL"] = db_url
            return self

        def __exit__(self, *exc):
            if self._prev is None:
                os.environ.pop("MC_DATABASE_URL", None)
            else:
                os.environ["MC_DATABASE_URL"] = self._prev

    return _Ctx()


def command_upgrade(db_url: str, revision: str = HEAD) -> None:
    from alembic import command

    with _with_db_url(db_url):
        command.upgrade(_config(db_url), revision)


def command_stamp(db_url: str, revision: str = HEAD) -> None:
    from alembic import command

    with _with_db_url(db_url):
        command.stamp(_config(db_url), revision)


def command_downgrade(db_url: str, revision: str) -> None:
    from alembic import command

    with _with_db_url(db_url):
        command.downgrade(_config(db_url), revision)


def _business_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _drop_orphan_alembic_version(engine: Engine) -> None:
    """``drop_all`` 不删 ``alembic_version``；无业务表时清版本表以便 upgrade 重建。"""
    from sqlalchemy import inspect, text

    names = set(inspect(engine).get_table_names())
    if "alembic_version" in names and not _business_tables(engine):
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def apply_schema_cutover(engine: Engine, db_url: str) -> str:
    """执行切流策略；返回模式标签供日志/测试。"""
    from .db import Base, migrate_schema

    empty = not _business_tables(engine)
    if empty:
        _drop_orphan_alembic_version(engine)
    if empty and alembic_available() and not _is_sqlite_memory(db_url):
        try:
            command_upgrade(db_url, HEAD)
            migrate_schema(engine)
            logger.info("AUD-2026-07: schema via alembic upgrade head")
            return "alembic_upgrade"
        except Exception as exc:  # noqa: BLE001 — 启动兜底
            logger.warning(
                "AUD-2026-07: alembic upgrade failed, fallback create_all: %s",
                exc,
            )

    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
    align_mode = align_alembic_version(engine, db_url)
    logger.info(
        "AUD-2026-07: schema via create_all+migrate_schema (alembic=%s)",
        align_mode,
    )
    return f"create_all_migrate:{align_mode}"


def align_alembic_version(engine: Engine, db_url: str) -> str:
    """已有业务表时对齐 alembic_version；不重跑 baseline DDL。"""
    if not alembic_available():
        return "unavailable"
    if _is_sqlite_memory(db_url):
        return "skipped_memory"
    names = set(inspect(engine).get_table_names())
    try:
        if "alembic_version" not in names:
            command_stamp(db_url, HEAD)
            return "stamp_head"
        command_upgrade(db_url, HEAD)
        return "upgrade_head"
    except Exception as exc:  # noqa: BLE001
        logger.warning("AUD-2026-07: alembic version align failed: %s", exc)
        return "align_failed"
