"""Align database startup with Alembic and adopt unversioned legacy schemas."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
HEAD = "head"


def _is_sqlite_memory(db_url: str) -> bool:
    """Alembic creates a separate connection, so it cannot migrate this in-memory schema."""
    url = (db_url or "").strip().lower()
    return url.startswith("sqlite") and (
        ":memory:" in url or url.rstrip("/") in {"sqlite://", "sqlite+pysqlite://"}
    )


def alembic_available() -> bool:
    if not ALEMBIC_INI.is_file():
        return False
    try:
        from alembic import command  # noqa: F401
    except ImportError:
        return False
    return True


def _config(db_url: str):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["database_url"] = db_url
    return cfg


def command_upgrade(db_url: str, revision: str = HEAD) -> None:
    from alembic import command

    command.upgrade(_config(db_url), revision)


def command_stamp(db_url: str, revision: str = HEAD) -> None:
    from alembic import command

    command.stamp(_config(db_url), revision)


def command_downgrade(db_url: str, revision: str) -> None:
    from alembic import command

    command.downgrade(_config(db_url), revision)


def _has_version_record(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).first() is not None


def _verify_head(engine: Engine, db_url: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    expected = set(ScriptDirectory.from_config(_config(db_url)).get_heads())
    with engine.connect() as conn:
        actual = set(MigrationContext.configure(conn).get_current_heads())
    if actual != expected:
        raise RuntimeError(
            f"Alembic revision mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )


def apply_schema_cutover(engine: Engine, db_url: str) -> str:
    """Upgrade tracked schemas first, or adopt a legacy schema after applying compatibility repairs."""
    from .db import Base, migrate_schema

    names = set(inspect(engine).get_table_names())
    empty = not (names - {"alembic_version"})
    versioned = "alembic_version" in names and _has_version_record(engine)
    memory = _is_sqlite_memory(db_url)
    available = alembic_available()

    if versioned and (memory or not available):
        raise RuntimeError("Alembic is required to upgrade this versioned database")
    if available and not memory and (versioned or empty):
        command_upgrade(db_url, HEAD)
        _verify_head(engine, db_url)
        migrate_schema(engine)
        logger.info("AUD-2026-07: schema via alembic upgrade head")
        return "alembic_upgrade"

    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
    if not available:
        align_mode = "unavailable"
    elif memory:
        align_mode = "skipped_memory"
    else:
        command_stamp(db_url, HEAD)
        _verify_head(engine, db_url)
        align_mode = "stamp_head"
    logger.info(
        "AUD-2026-07: schema via create_all+migrate_schema (alembic=%s)",
        align_mode,
    )
    return f"create_all_migrate:{align_mode}"
