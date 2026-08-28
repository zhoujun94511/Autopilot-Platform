"""AUD-2026-07：init_db Alembic 切流。"""

from __future__ import annotations

import pytest

pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, text

from autopilot_platform.platform.core.alembic_align import (
    apply_schema_cutover,
    command_downgrade,
    command_upgrade,
)
from autopilot_platform.platform.core.db import init_db, reset_engine, session_factory


@pytest.fixture()
def scratch_url(tmp_path, monkeypatch):
    db_path = tmp_path / "cutover.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_DATABASE_URL", url)
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    reset_engine()
    yield url
    reset_engine()


def test_init_db_empty_creates_alembic_version(scratch_url):
    init_db(scratch_url)
    eng = create_engine(scratch_url)
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    assert "alembic_version" in names
    assert "users" in names
    assert "jobs" in names
    assert "design_documents" in names
    factory = session_factory()
    assert factory is not None


def test_legacy_db_stamps_without_rerunning_baseline(scratch_url):
    """已有业务表、无 alembic_version → stamp，不因 baseline 冲突失败。"""
    from autopilot_platform.platform.core.db import Base, get_engine, migrate_schema
    import autopilot_platform.platform.core.models  # noqa: F401  # pyright: ignore[reportUnusedImport]
    import autopilot_platform.platform.design.design_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

    engine = get_engine(scratch_url)
    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
    assert "alembic_version" not in set(inspect(engine).get_table_names())

    mode = apply_schema_cutover(engine, scratch_url)
    assert mode.startswith("create_all_migrate")
    names = set(inspect(engine).get_table_names())
    assert "alembic_version" in names
    with engine.connect() as conn:
        ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert ver == "f0b8c7d6e5a4"


def test_scratch_upgrade_downgrade_upgrade_drill(tmp_path, monkeypatch):
    """回滚演练：upgrade → downgrade base → upgrade。"""
    db_path = tmp_path / "drill.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_DATABASE_URL", url)
    command_upgrade(url, "head")
    assert db_path.is_file()
    command_downgrade(url, "base")
    eng = create_engine(url)
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    # downgrade base 后业务表应清空；version 表可能仍在
    assert "users" not in names
    command_upgrade(url, "head")
    eng = create_engine(url)
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    assert "users" in names
    assert "alembic_version" in names
