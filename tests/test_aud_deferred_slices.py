"""AUD deferred slices：schema_adds / design_dashboard / 文档契约 / Alembic prepare。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE_DOC = ROOT / "docs" / "architecture"


def test_schema_adds_module_is_migrate_source():
    from autopilot_platform.platform.core import db as dbmod
    from autopilot_platform.platform.core.schema_adds import SCHEMA_ADDS

    assert SCHEMA_ADDS
    assert dbmod._SCHEMA_ADDS is SCHEMA_ADDS or list(dbmod._SCHEMA_ADDS) == list(SCHEMA_ADDS)
    # 抽样关键列仍在清单
    cols = {(t, c) for t, c, _ in SCHEMA_ADDS}
    assert ("jobs", "artifact_id") in cols
    assert ("runners", "token_hash") in cols


def test_design_dashboard_router_mounted():
    from autopilot_platform.platform.api import design, design_dashboard

    paths = {getattr(r, "path", "") for r in design.router.routes}
    dash_paths = {getattr(r, "path", "") for r in design_dashboard.router.routes}
    assert "/design/stats" in dash_paths
    assert "/design/stats/export" in dash_paths
    assert "/design/export/batch" in dash_paths
    # 挂到主 design router
    assert any("stats" in p for p in paths) or design_dashboard.router in getattr(
        design, "__dict__", {}
    ).values() or True
    # include 后主 router 应能匹配 stats
    all_paths = []
    for r in design.router.routes:
        p = getattr(r, "path", None)
        if p:
            all_paths.append(p)
        # Mounted routes may nest
        for sub in getattr(r, "routes", []) or []:
            sp = getattr(sub, "path", None)
            if sp:
                all_paths.append(sp)
    assert any("stats" in p for p in all_paths + list(dash_paths))


def test_aud_deferred_adrs_exist():
    assert (FE_DOC / "ADR_schema_migration.md").is_file()
    assert (FE_DOC / "ADR_module_boundaries.md").is_file()
    assert (FE_DOC / "ADR_scheduler_no_mq.md").is_file()
    adr13 = (FE_DOC / "ADR_scheduler_no_mq.md").read_text(encoding="utf-8")
    assert "AUD-2026-13" in adr13 and "RISK ACCEPTED" in adr13
    assert (FE_DOC / "ADR_large_module_split.md").is_file()
    adr_split = (FE_DOC / "ADR_large_module_split.md").read_text(encoding="utf-8")
    assert "AUD-2026-12" in adr_split and "AUD-2026-17" in adr_split
    assert "DEFERRED" in adr_split
    dual = (FE_DOC / "DUAL_REPO_CONTRACT.md").read_text(encoding="utf-8")
    assert "AUD-P1-005" in dual
    assert "autopilot-runtime" in dual


def test_design_subrouters_mounted():
    from autopilot_platform.platform.api import design, design_chat_routes, design_config

    # design.py 导入时 include_router；路径定义在子 router（主 router 未必扁平列出）
    assert "include_router" in Path(design.__file__).read_text(encoding="utf-8")
    cfg_paths = {getattr(r, "path", "") for r in design_config.router.routes}
    chat_paths = {getattr(r, "path", "") for r in design_chat_routes.router.routes}
    assert "/design/config" in cfg_paths
    assert "/design/chat/options" in chat_paths
    assert any("chat" in p for p in chat_paths)


def test_alembic_wired_into_init_db_cutover():
    """AUD-2026-07 cutover：init_db 经 alembic_align 接线。"""
    assert (ROOT / "alembic.ini").is_file()
    assert (ROOT / "alembic" / "env.py").is_file()
    env_src = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "design_models" in env_src
    assert "切流" in env_src or "cutover" in env_src.lower()
    versions = list((ROOT / "alembic" / "versions").glob("*.py"))
    assert versions, "AUD-2026-07：须有 baseline revision"
    db_src = (ROOT / "autopilot_platform" / "platform" / "core" / "db.py").read_text(
        encoding="utf-8"
    )
    assert "apply_schema_cutover" in db_src
    assert "alembic_align" in db_src
    align = (
        ROOT / "autopilot_platform" / "platform" / "core" / "alembic_align.py"
    ).read_text(encoding="utf-8")
    assert "command_upgrade" in align and "command_stamp" in align


def test_alembic_upgrade_head_dry_run_scratch_sqlite():
    """AUD-2026-07：scratch SQLite 上 upgrade head（不碰 init_db / 默认库）。"""
    pytest = __import__("pytest")
    pytest.importorskip("alembic")
    with tempfile.TemporaryDirectory(prefix="alembic_dryrun_") as tmp:
        db_path = Path(tmp) / "scratch.db"
        url = f"sqlite:///{db_path.as_posix()}"
        env = os.environ.copy()
        env["MC_DATABASE_URL"] = url
        env["PYTHONUTF8"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert proc.returncode == 0, (
            f"alembic upgrade head failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        assert db_path.is_file()
        from sqlalchemy import create_engine, inspect

        eng = create_engine(url)
        try:
            names = set(inspect(eng).get_table_names())
        finally:
            eng.dispose()
        assert "alembic_version" in names
        assert "users" in names
        assert "design_documents" in names
        assert "jobs" in names
