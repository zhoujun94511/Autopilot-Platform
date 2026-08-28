"""tools/init_platform.py 白盒（临时目录，不碰默认库）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def isolated_platform_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir()
    db = data / "test.db"
    cfg = data / "mc_runtime_config.json"
    monkeypatch.setenv("MC_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(cfg))
    monkeypatch.setenv("MC_DATA_DIR", str(data))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    # 清掉可能已初始化的引擎 / 配置缓存
    from autopilot_platform.platform.core.db import reset_engine

    reset_engine()
    yield {"data": data, "db": db, "cfg": cfg}
    reset_engine()


def test_init_platform_init_and_status(isolated_platform_env):
    from tools import init_platform as m

    assert m.cmd_init(with_config=True, with_vector=True) == 0
    assert isolated_platform_env["db"].is_file()
    assert isolated_platform_env["cfg"].is_file()
    assert m.cmd_status() == 0
    assert m.cmd_migrate() == 0


def test_init_platform_config_force_and_seed(isolated_platform_env):
    from tools import init_platform as m

    assert m.cmd_config(force=False, seed_defaults=False) == 0
    isolated_platform_env["cfg"].write_text(
        '{"AP_AI_PROVIDER": "openai"}\n', encoding="utf-8"
    )
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    assert m.cmd_config(force=True, seed_defaults=False) == 0
    text = isolated_platform_env["cfg"].read_text(encoding="utf-8")
    assert text.strip() in ("{}",)
    # 应有备份
    baks = list(isolated_platform_env["data"].glob("mc_runtime_config.json.bak.*"))
    assert baks
    assert m.cmd_config(force=False, seed_defaults=True) == 0


def test_init_platform_clear_requires_yes(isolated_platform_env):
    from tools import init_platform as m

    m.cmd_init()
    assert m.cmd_clear_data(yes=False) == 2
    assert m.cmd_reset(yes=False) == 2
    assert m.cmd_clear_data(yes=True, keep_admin=True) == 0


def test_init_platform_fresh_rebuilds_after_drop(isolated_platform_env):
    """fresh/reset：drop_all 后须能重建 users（勿留孤儿 alembic_version）。"""
    from sqlalchemy import func, select

    from autopilot_platform.platform.core.db import init_db, reset_engine, session_factory
    from autopilot_platform.platform.core.models import UserRow
    from tools import init_platform as m

    assert m.cmd_init() == 0
    assert m.cmd_fresh(yes=True) == 0
    reset_engine()
    init_db()
    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        n = int(db.scalar(select(func.count()).select_from(UserRow)) or 0)
        admin = db.scalars(select(UserRow).where(UserRow.username == "admin")).first()
    finally:
        db.close()
    assert n == 1
    assert admin is not None
    assert admin.role == "admin"


def test_readme_lists_init_platform():
    text = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "init_platform.py" in text
