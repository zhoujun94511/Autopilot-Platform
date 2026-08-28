#!/usr/bin/env python3
r"""Platform 本地 ``data/`` 初始化与维护（主库 / 向量索引 / 运维 JSON / bootstrap admin）。

在仓库根执行。Windows 用 ``.venv\Scripts\python.exe``；Linux/macOS 改为 ``.venv/bin/python``。

本地数据目录（默认 ``<仓库根>/data/``，gitignore；可用 ``MC_DATA_DIR`` 覆盖）::

  data/autopilot_platform.db          主业务库（用户、组织、项目、Job、设计域…）
  data/rag_index/vectors.sqlite       知识库向量索引
  data/mc_runtime_config.json         Web 运维运行时覆盖（可为 ``{}``）
  data/artifacts/ …                   制品等（init 后按需生成）

────────────────────────────────────────────────────────────────────────
一、日常（复制即用）
────────────────────────────────────────────────────────────────────────

新克隆 / 删过 ``data/`` 文件夹 — 先建仓再 ``start_dev.py``::

  .venv\Scripts\python.exe tools\init_platform.py init

开发清库重来（删表重建，仅留 admin，清空运维 JSON 覆盖）::

  .venv\Scripts\python.exe tools\init_platform.py fresh --yes

查看库与目录状态（只读，不改数据）::

  .venv\Scripts\python.exe tools\init_platform.py status

默认管理员：``admin`` / ``admin``（或 ``.env`` 里 ``MC_ADMIN_USER`` / ``MC_ADMIN_PASSWORD``）

────────────────────────────────────────────────────────────────────────
二、全部子命令
────────────────────────────────────────────────────────────────────────

status
  只读：``data_dir``、库 URL、表数量、users 数、bootstrap admin、抽样业务表行数、
  ``mc_runtime_config.json`` 覆盖键数、``vectors.sqlite`` 条目数。

  .venv\Scripts\python.exe tools\init_platform.py status

init
  建表 + Alembic/迁移 + bootstrap admin + 空 ``mc_runtime_config.json`` + 向量库骨架。
  已有库时幂等，**不删**已有业务数据。

  .venv\Scripts\python.exe tools\init_platform.py init
  .venv\Scripts\python.exe tools\init_platform.py init --skip-config   # 不碰 mc_runtime_config.json
  .venv\Scripts\python.exe tools\init_platform.py init --skip-vector   # 不建 vectors.sqlite

migrate
  拉代码升级后：仅 ``db.migrate_schema`` 补缺失列，不删数据。

  .venv\Scripts\python.exe tools\init_platform.py migrate

config
  运维 JSON（``data/mc_runtime_config.json``）：Web 界面保存的运行时覆盖，**不是**主库。

  .venv\Scripts\python.exe tools\init_platform.py config
  .venv\Scripts\python.exe tools\init_platform.py config --force
      # 清空全部 Web 覆盖；已有文件先备份为 mc_runtime_config.json.bak.<UTC 时间>
  .venv\Scripts\python.exe tools\init_platform.py config --seed-defaults
      # 把非密钥默认值写入 JSON（跳过已有键与 SECRET_KEYS）

vector-init
  仅确保 ``data/rag_index/vectors.sqlite`` 表结构存在（``init`` 已包含时可单独重跑）。

  .venv\Scripts\python.exe tools\init_platform.py vector-init

clear-data
  DELETE 业务表数据，**保留表结构**；须 ``--yes``。默认**保留** ``users``（含 admin）。

  .venv\Scripts\python.exe tools\init_platform.py clear-data --yes
  .venv\Scripts\python.exe tools\init_platform.py clear-data --yes --drop-users
      # 连 users 一并清空，随后 recreate bootstrap admin

reset
  危险：``drop_all`` 删表 + 重建 schema + 空配置骨架 + 向量骨架；**不清**运维 JSON 内容。
  须 ``--yes``。一般开发重置用 ``fresh`` 即可。

  .venv\Scripts\python.exe tools\init_platform.py reset --yes

fresh
  ``reset --yes`` + ``config --force``：删表重建 + 清空运维 JSON + 仅 bootstrap admin。
  开发「一键恢复干净环境」推荐用这个。

  .venv\Scripts\python.exe tools\init_platform.py fresh --yes

migrate-data
  一次性：旧路径 ``autopilot_platform/data/`` → 仓库根 ``data/``（统一存储目录后遗留时用）。

  .venv\Scripts\python.exe tools\init_platform.py migrate-data --yes

────────────────────────────────────────────────────────────────────────
三、环境变量（自动读仓库根 ``.env``）
────────────────────────────────────────────────────────────────────────

  MC_DATA_DIR          数据根目录（默认 ``./data``）
  MC_DATABASE_URL      主库连接（默认 ``data/autopilot_platform.db``）
  MC_RUNTIME_CONFIG    运维 JSON 路径（默认 ``data/mc_runtime_config.json``）
  MC_ADMIN_USER        bootstrap 管理员用户名（默认 admin）
  MC_ADMIN_PASSWORD    bootstrap 管理员密码（默认 admin）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_env() -> None:
    try:
        from autopilot_platform.platform.core.env_file import load_project_dotenv

        load_project_dotenv()
    except (ImportError, OSError, TypeError, ValueError, RuntimeError):
        pass


def _print(msg: str) -> None:
    print(msg)


def cmd_status() -> int:
    from sqlalchemy import func, inspect, select, text

    from autopilot_platform.platform.core.db import get_engine, init_db, session_factory
    from autopilot_platform.platform.core.models import UserRow
    from autopilot_platform.platform.core.settings import (
        bootstrap_admin_username,
        data_dir,
        database_url,
    )
    from autopilot_platform.platform.ops.runtime_config import (
        load_runtime_config,
        runtime_config_path,
    )
    from autopilot_platform.platform.rag import vector_index_sqlite as vis

    url = database_url()
    root = data_dir()
    _print("== Platform init status ==")
    _print(f"data_dir:     {root}")
    _print(f"database_url: {url}")
    try:
        init_db()
        engine = get_engine()
        inspector = inspect(engine)
        tables = sorted(inspector.get_table_names())
        _print(f"tables: {len(tables)}")
        factory = session_factory()
        users = 0
        admin = None
        if factory is not None:
            db = factory()
            try:
                users = int(db.scalar(select(func.count()).select_from(UserRow)) or 0)
                admin = db.scalars(
                    select(UserRow).where(UserRow.username == bootstrap_admin_username())
                ).first()
            finally:
                db.close()
        _print(f"users: {users}")
        _print(
            f"bootstrap_admin ({bootstrap_admin_username()}): "
            f"{'present' if admin else 'missing'}"
        )
        # 抽样业务表行数
        sample = ("projects", "jobs", "design_knowledge_items", "organizations")
        with engine.connect() as conn:
            for t in sample:
                if t not in tables:
                    continue
                n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                _print(f"  {t}: {n}")
    except Exception as e:  # noqa: BLE001
        _print(f"database: ERROR {e}")
        return 1

    cfg_path = runtime_config_path()
    overrides = load_runtime_config()
    _print(f"runtime_config: {cfg_path}")
    _print(f"  exists: {cfg_path.is_file()}  override_keys: {len(overrides)}")

    vector_path = vis.db_path()
    _print(f"vector_index: {vector_path}")
    _print(f"  exists: {vector_path.is_file()}")
    if vector_path.is_file():
        import sqlite3

        conn = sqlite3.connect(str(vector_path))
        try:
            n = conn.execute("SELECT COUNT(*) FROM index_items").fetchone()[0]
            p = conn.execute("SELECT COUNT(DISTINCT project_id) FROM index_items").fetchone()[0]
            _print(f"  index_items: {n}  projects: {p}")
        except (OSError, sqlite3.Error) as e:
            _print(f"  read ERROR: {e}")
        finally:
            conn.close()
    return 0


def cmd_init(*, with_config: bool = True, with_vector: bool = True) -> int:
    from autopilot_platform.platform.core.db import init_db
    from autopilot_platform.platform.core.settings import (
        bootstrap_admin_password,
        bootstrap_admin_username,
        database_url,
    )

    _print(f"init database: {database_url()}")
    init_db()
    _print(
        f"OK: schema ready; bootstrap admin user={bootstrap_admin_username()!r} "
        f"(password from MC_ADMIN_PASSWORD, default {bootstrap_admin_password()!r})"
    )
    if with_config:
        cmd_config(force=False, seed_defaults=False)
    if with_vector:
        cmd_vector_init()
    return 0


def cmd_migrate() -> int:
    from autopilot_platform.platform.core.db import get_engine, init_db, migrate_schema

    init_db()  # ensure engine + models loaded
    applied = migrate_schema(get_engine())
    if applied:
        _print("migrated columns:")
        for a in applied:
            _print(f"  + {a}")
    else:
        _print("OK: schema already up to date (no ADD COLUMN)")
    return 0


def _backup_file(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, bak)
    return bak


def cmd_config(*, force: bool = False, seed_defaults: bool = False) -> int:
    """初始化 / 重置运维运行时配置文件（对标 init_config_center）。"""
    from autopilot_platform.platform.ops.runtime_config import (
        EDITABLE_KEYS,
        SECRET_KEYS,
        describe_config,
        load_runtime_config,
        reload_runtime_config,
        runtime_config_path,
        save_runtime_config,
    )

    path = runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if force:
        bak = _backup_file(path)
        if bak:
            _print(f"backed up: {bak}")
        path.write_text("{}\n", encoding="utf-8")
        reload_runtime_config()
        _print(f"OK: cleared runtime overrides → {path}")
    elif not path.is_file():
        path.write_text("{}\n", encoding="utf-8")
        reload_runtime_config()
        _print(f"OK: created empty runtime config → {path}")
    else:
        _print(f"OK: runtime config exists → {path} (keys={len(load_runtime_config())})")

    if seed_defaults:
        desc = describe_config()
        values = dict(desc.get("values") or {})
        cur = load_runtime_config()
        updates: dict[str, Any] = {}
        for k in EDITABLE_KEYS:
            if k in SECRET_KEYS:
                continue
            if k in cur:
                continue
            v = values.get(k)
            if v is None or str(v).strip() == "":
                continue
            updates[k] = v
        if updates:
            save_runtime_config(updates, replace=False)
            _print(f"OK: seeded {len(updates)} non-secret default overrides")
        else:
            _print("OK: nothing to seed (already set or empty defaults)")
    return 0


def cmd_vector_init() -> int:
    from autopilot_platform.platform.rag import vector_index_sqlite as vis

    path = vis.ensure_db()
    _print(f"OK: vector index schema ready → {path}")
    return 0


def cmd_clear_data(*, yes: bool, keep_admin: bool = True) -> int:
    """清空业务数据，保留表结构；默认保留用户表（bootstrap admin）。"""
    if not yes:
        _print("拒绝：清空数据需加 --yes")
        return 2

    from sqlalchemy import inspect, text

    from autopilot_platform.platform.core.db import get_engine, init_db

    init_db()
    engine = get_engine()
    tables = sorted(inspect(engine).get_table_names())
    skip = {"users"} if keep_admin else set()
    deleted = 0
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        # 先删有外键依赖的，简单起见按名字倒序 + 多轮
        for _ in range(3):
            for t in reversed(tables):
                if t in skip or t.startswith("sqlite_"):
                    continue
                try:
                    conn.execute(text(f"DELETE FROM {t}"))
                    deleted += 1
                except (OSError, RuntimeError):
                    continue
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=ON"))
    _print(f"OK: cleared data from ~{deleted} table passes (keep_admin={keep_admin})")
    if keep_admin:
        from autopilot_platform.platform.core.db import ensure_bootstrap_admin

        ensure_bootstrap_admin()
    return 0


def cmd_reset(*, yes: bool) -> int:
    """删除全部表并重建（危险）。SQLite 也可直接删文件。"""
    if not yes:
        _print("拒绝：reset 需加 --yes")
        return 2

    from autopilot_platform.platform.core.db import Base, get_engine, init_db, reset_engine
    from autopilot_platform.platform.core.settings import database_url
    from sqlalchemy import text

    url = database_url()
    _print(f"reset database: {url}")
    reset_engine()
    init_db()  # load models onto metadata
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    reset_engine()
    init_db()
    cmd_config(force=False, seed_defaults=False)
    cmd_vector_init()
    _print("OK: database reset + schema recreated")
    return 0


def cmd_fresh(*, yes: bool) -> int:
    """删表重建 + 初始 admin + 清空运维覆盖 + 空向量库。"""
    if not yes:
        _print("拒绝：fresh 需加 --yes")
        return 2
    rc = cmd_reset(yes=True)
    if rc != 0:
        return rc
    cmd_config(force=True, seed_defaults=False)
    from autopilot_platform.platform.core.settings import (
        bootstrap_admin_password,
        bootstrap_admin_username,
    )

    _print(
        f"OK: fresh 完成 — 仅用户 {bootstrap_admin_username()!r} "
        f"(密码见 MC_ADMIN_PASSWORD，默认 {bootstrap_admin_password()!r})"
    )
    return 0


def cmd_migrate_data(*, yes: bool) -> int:
    """``autopilot_platform/data/`` → ``data/`` 一次性迁移。"""
    if not yes:
        _print("拒绝：migrate-data 需加 --yes")
        return 2

    from autopilot_platform.platform.core.settings import (
        data_dir,
        default_data_dir,
        legacy_data_dir,
    )

    legacy = legacy_data_dir()
    unified = data_dir() if os.environ.get("MC_DATA_DIR") else default_data_dir()
    if not legacy.is_dir():
        _print(f"OK: 无旧目录 {legacy}")
        return 0
    if legacy.resolve() == unified.resolve():
        _print("OK: 已在统一 data 目录")
        return 0
    unified.mkdir(parents=True, exist_ok=True)
    moved = 0
    for item in legacy.iterdir():
        dest = unified / item.name
        if dest.exists():
            if item.name == "autopilot_platform.db":
                try:
                    if item.stat().st_mtime > dest.stat().st_mtime:
                        bak = dest.with_name(f"{dest.name}.pre_migrate.bak")
                        shutil.copy2(dest, bak)
                        dest.unlink()
                        _print(f"  备份旧库: {bak.name}")
                    else:
                        _print("跳过 autopilot_platform.db（data/ 中已有较新库）")
                        continue
                except OSError as e:
                    _print(f"跳过 autopilot_platform.db: {e}")
                    continue
            else:
                _print(f"跳过（目标已存在）: {item.name}")
                continue
        shutil.move(str(item), str(dest))
        moved += 1
        _print(f"  迁移: {item.name}")
    if moved:
        _print(f"OK: 已迁移 {moved} 项 → {unified}")
        _print("建议：确认 status 正常后手动删除空目录 autopilot_platform/data/")
    else:
        _print("OK: 无需迁移（目标已齐全或旧目录为空）")
    return 0


def main(argv: list[str] | None = None) -> int:
    _bootstrap_env()
    epilog = r"""
命令一览（Windows 路径；Linux/macOS 改 .venv/bin/python）:

  status
    .venv\Scripts\python.exe tools\init_platform.py status

  init — 新克隆/无 data/，不删已有数据
    .venv\Scripts\python.exe tools\init_platform.py init
    .venv\Scripts\python.exe tools\init_platform.py init --skip-config
    .venv\Scripts\python.exe tools\init_platform.py init --skip-vector

  migrate — 升级后仅补缺失列
    .venv\Scripts\python.exe tools\init_platform.py migrate

  config — 运维 JSON（Web 运行时覆盖）
    .venv\Scripts\python.exe tools\init_platform.py config
    .venv\Scripts\python.exe tools\init_platform.py config --force
    .venv\Scripts\python.exe tools\init_platform.py config --seed-defaults

  vector-init
    .venv\Scripts\python.exe tools\init_platform.py vector-init

  clear-data — 清业务数据，保留表（须 --yes）
    .venv\Scripts\python.exe tools\init_platform.py clear-data --yes
    .venv\Scripts\python.exe tools\init_platform.py clear-data --yes --drop-users

  reset — 删表重建，不清运维 JSON（须 --yes）
    .venv\Scripts\python.exe tools\init_platform.py reset --yes

  fresh — 开发一键清库（reset + 清 JSON + admin）（须 --yes）
    .venv\Scripts\python.exe tools\init_platform.py fresh --yes

  migrate-data — autopilot_platform/data → data/（须 --yes）
    .venv\Scripts\python.exe tools\init_platform.py migrate-data --yes

详见脚本顶部 docstring。
"""
    ap = argparse.ArgumentParser(
        description="Platform 数据库 init / fresh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "status",
        help="只读：库 URL、表数、users、bootstrap admin、抽样行数、配置键、向量索引",
    )
    p_init = sub.add_parser(
        "init",
        help="建表 + migrate + bootstrap admin + 空运维配置 + 向量骨架（已有库时幂等）",
    )
    p_init.add_argument(
        "--skip-config",
        action="store_true",
        help="跳过 mc_runtime_config.json 初始化",
    )
    p_init.add_argument(
        "--skip-vector",
        action="store_true",
        help="跳过 data/rag_index/vectors.sqlite 骨架",
    )

    sub.add_parser(
        "migrate",
        help="仅 db.migrate_schema 增量 ADD COLUMN（不删数据）",
    )

    p_cfg = sub.add_parser(
        "config",
        help="初始化 data/mc_runtime_config.json（Web 运维运行时覆盖，非 DB 表）",
    )
    p_cfg.add_argument(
        "--force",
        action="store_true",
        help="清空全部运行时覆盖；已有文件先备份为 .bak.<UTC 时间戳>",
    )
    p_cfg.add_argument(
        "--seed-defaults",
        action="store_true",
        help="写入非密钥默认覆盖（跳过 SECRET_KEYS 与已有键）",
    )

    sub.add_parser(
        "vector-init",
        help="确保 data/rag_index/vectors.sqlite 表结构存在",
    )

    p_clear = sub.add_parser(
        "clear-data",
        help="DELETE 业务表数据，保留表结构；默认保留 users",
    )
    p_clear.add_argument(
        "--yes",
        action="store_true",
        help="确认执行（无此 flag 则拒绝）",
    )
    p_clear.add_argument(
        "--drop-users",
        action="store_true",
        help="连同 users 清空，随后 ensure_bootstrap_admin 重建 admin",
    )

    p_fresh = sub.add_parser(
        "fresh",
        help="清数据、重建表、初始 admin（一条命令，开发重置用）",
    )
    p_fresh.add_argument("--yes", action="store_true", help="确认执行")

    p_migrate_data = sub.add_parser(
        "migrate-data",
        help="autopilot_platform/data → data/ 一次性目录迁移",
    )
    p_migrate_data.add_argument("--yes", action="store_true", help="确认执行")

    p_reset = sub.add_parser(
        "reset",
        help="drop_all + 重建 schema + 空配置 + 向量骨架（开发重置，危险）",
    )
    p_reset.add_argument(
        "--yes",
        action="store_true",
        help="确认执行（无此 flag 则拒绝）",
    )

    args = ap.parse_args(argv)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "init":
        return cmd_init(
            with_config=not args.skip_config,
            with_vector=not args.skip_vector,
        )
    if args.cmd == "migrate":
        return cmd_migrate()
    if args.cmd == "config":
        return cmd_config(force=args.force, seed_defaults=args.seed_defaults)
    if args.cmd == "vector-init":
        return cmd_vector_init()
    if args.cmd == "clear-data":
        return cmd_clear_data(yes=args.yes, keep_admin=not args.drop_users)
    if args.cmd == "fresh":
        return cmd_fresh(yes=args.yes)
    if args.cmd == "migrate-data":
        return cmd_migrate_data(yes=args.yes)
    if args.cmd == "reset":
        return cmd_reset(yes=args.yes)
    return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        pass
    raise SystemExit(main())
