"""SQLAlchemy 引擎与会话。"""

from __future__ import annotations

from collections.abc import Generator
from typing import Optional

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .settings import database_url


class Base(DeclarativeBase):
    """ORM 声明基类（DeclarativeBase 便于 Mapped[] / Session.get 类型推断）。"""


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def session_factory() -> sessionmaker[Session] | None:
    """已初始化时返回 sessionmaker；未 init 时为 None。"""
    return _SessionLocal

# (table, column, SQL type fragment for ADD COLUMN)
from .schema_adds import SCHEMA_ADDS as _SCHEMA_ADDS


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    # 已初始化且未显式换 URL 时复用，避免测试里 get_engine() 落到默认库。
    if url is None and _engine is not None:
        return _engine
    db_url = url or database_url()
    connect_args: dict = {}
    kwargs: dict = {"future": True}
    sqlite_memory = ":memory:" in db_url or db_url.rstrip("/") in (
        "sqlite://",
        "sqlite+pysqlite://",
    )
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # :memory: 默认每连接一块空库；应用内必须共用同一连接池。
        if sqlite_memory:
            kwargs["poolclass"] = StaticPool
    else:
        # PostgreSQL / 其它：断线重连探测
        kwargs["pool_pre_ping"] = True
    engine = create_engine(db_url, connect_args=connect_args, **kwargs)

    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL 需要文件库；:memory: 不支持。busy_timeout 减轻单写者排队。
            if not sqlite_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine


def _table_columns(engine: Engine, table: str) -> set[str]:
    insp = inspect(engine)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def migrate_schema(engine: Engine) -> list[str]:
    """为已有库补齐增量列（SQLite / PostgreSQL 等，基于 Inspector）。

    返回实际执行的 ``table.column`` 列表。新库依赖 ``create_all``，此处幂等。
    """
    applied: list[str] = []
    # 按表缓存列，减少 inspect 次数
    col_cache: dict[str, set[str]] = {}
    with engine.begin() as conn:
        for table, column, typ in _SCHEMA_ADDS:
            cols = col_cache.get(table)
            if cols is None:
                cols = _table_columns(engine, table)
                col_cache[table] = cols
            if not cols or column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {typ}"))
            cols.add(column)
            applied.append(f"{table}.{column}")
        if engine.dialect.name in {"sqlite", "postgresql"} and _table_columns(
            engine, "device_reservations"
        ):
            # 旧实现可能在极窄竞态下留下多个 active；先确定性保留最新一条，
            # 再建立部分唯一索引，避免升级时因历史脏数据启动失败。
            conn.execute(
                text(
                    "UPDATE device_reservations SET status = 'expired', "
                    "released_at = CURRENT_TIMESTAMP WHERE id IN ("
                    "SELECT id FROM ("
                    "SELECT id, ROW_NUMBER() OVER (PARTITION BY device_id "
                    "ORDER BY start_at DESC, id DESC) AS rn "
                    "FROM device_reservations WHERE status = 'active'"
                    ") ranked WHERE rn > 1)"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_reservation_active "
                    "ON device_reservations (device_id) WHERE status = 'active'"
                )
            )
            if "reservation_id" in _table_columns(engine, "devices"):
                conn.execute(
                    text(
                        "UPDATE devices SET reservation_id = ("
                        "SELECT id FROM device_reservations "
                        "WHERE device_reservations.device_id = devices.id "
                        "AND status = 'active' ORDER BY start_at DESC, id DESC LIMIT 1"
                        ") WHERE reservation_id IS NULL"
                    )
                )
        apply_concurrency_indexes(conn)
        applied.extend(_widen_backend_mode_columns(engine, conn))
    return applied


def _widen_backend_mode_columns(engine: Engine, conn) -> list[str]:
    """旧库 jobs/schedules.backend_mode VARCHAR(32) → 64（仅 PostgreSQL 强制长度）。"""
    from autopilot_platform.core.job_platforms import BACKEND_MODE_MAX_LEN

    if engine.dialect.name != "postgresql":
        return []
    applied: list[str] = []
    insp = inspect(engine)
    insp.clear_cache()
    names = set(insp.get_table_names())
    for table in ("jobs", "schedules"):
        if table not in names:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        col = cols.get("backend_mode")
        if col is None:
            continue
        length = getattr(col.get("type"), "length", None)
        if length is not None and int(length) >= BACKEND_MODE_MAX_LEN:
            continue
        conn.execute(
            text(
                f"ALTER TABLE {table} ALTER COLUMN backend_mode "
                f"TYPE VARCHAR({BACKEND_MODE_MAX_LEN})"
            )
        )
        applied.append(f"{table}.backend_mode:{BACKEND_MODE_MAX_LEN}")
    return applied


def apply_concurrency_indexes(conn) -> None:
    """成员/OIDC/设备唯一约束与 jobs(status, created_at) 索引；幂等。

    Alembic revision 与 ``migrate_schema`` 共用，避免 stamp-head 旧库漏索引。
    旧库若缺列（例如仅有 ``devices.id`` 的预约迁移夹具）则跳过对应索引。
    """
    insp = inspect(conn)
    insp.clear_cache()
    names = set(insp.get_table_names())

    def _cols(table: str) -> set[str]:
        if table not in names:
            return set()
        # 同一事务里刚 ALTER 的列：SQLite Inspector 可能仍缓存旧表结构。
        if conn.dialect.name == "sqlite":
            return {
                row[1]
                for row in conn.execute(text(f'PRAGMA table_info("{table}")'))
            }
        insp.clear_cache()
        return {c["name"] for c in insp.get_columns(table)}

    def _exec(sql: str) -> None:
        conn.execute(text(sql))

    org_cols = _cols("organization_members")
    if {"org_id", "user_id"} <= org_cols:
        _exec(
            "DELETE FROM organization_members WHERE id NOT IN ("
            "SELECT MIN(id) FROM organization_members GROUP BY org_id, user_id)"
        )
        _exec(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_org_member_user "
            "ON organization_members (org_id, user_id)"
        )
    proj_cols = _cols("project_members")
    if {"project_id", "user_id"} <= proj_cols:
        _exec(
            "DELETE FROM project_members WHERE id NOT IN ("
            "SELECT MIN(id) FROM project_members GROUP BY project_id, user_id)"
        )
        _exec(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_member_user "
            "ON project_members (project_id, user_id)"
        )
    device_cols = _cols("devices")
    if {"runner_id", "udid"} <= device_cols:
        busy_ord = (
            "CASE WHEN busy_job_id IS NOT NULL AND busy_job_id != '' THEN 0 ELSE 1 END"
            if "busy_job_id" in device_cols
            else "0"
        )
        time_ord = "updated_at DESC" if "updated_at" in device_cols else "id DESC"
        _exec(
            "DELETE FROM devices WHERE id NOT IN ("
            "SELECT id FROM ("
            "SELECT id, ROW_NUMBER() OVER ("
            f"PARTITION BY runner_id, udid "
            f"ORDER BY {busy_ord}, {time_ord}, id) AS rn "
            "FROM devices) ranked WHERE rn = 1)"
        )
        _exec(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_runner_udid "
            "ON devices (runner_id, udid)"
        )
    user_cols = _cols("users")
    if "oidc_sub" in user_cols:
        _exec(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_oidc_sub "
            "ON users (oidc_sub) WHERE oidc_sub != ''"
        )
    if "saml_nameid" in user_cols:
        _exec(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_saml_nameid "
            "ON users (saml_nameid) WHERE saml_nameid != ''"
        )
    job_cols = _cols("jobs")
    if {"status", "created_at"} <= job_cols:
        _exec(
            "CREATE INDEX IF NOT EXISTS ix_jobs_status_created_at "
            "ON jobs (status, created_at)"
        )


def _migrate_sqlite(engine: Engine) -> None:
    """兼容旧调用名；实际走通用 migrate_schema。"""
    migrate_schema(engine)


def ensure_bootstrap_admin() -> None:
    """若无用户则创建默认 admin（可用 MC_ADMIN_USER / MC_ADMIN_PASSWORD 覆盖）。"""
    from .models import UserRow, new_id
    from .security import hash_password
    from .settings import bootstrap_admin_password, bootstrap_admin_username

    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        from sqlalchemy import select

        existing = db.scalars(select(UserRow).limit(1)).first()
        if existing is not None:
            return
        db.add(
            UserRow(
                id=new_id(),
                username=bootstrap_admin_username(),
                password_hash=hash_password(bootstrap_admin_password()),
                role="admin",
            )
        )
        db.commit()
    finally:
        db.close()


def init_db(url: str | None = None) -> None:
    """初始化库表（AUD-2026-07 切流：见 ``alembic_align.apply_schema_cutover``）。"""
    engine = get_engine(url)
    from . import models  # noqa: F401
    from ..design import design_models  # noqa: F401
    from .alembic_align import apply_schema_cutover

    db_url = url or database_url()
    apply_schema_cutover(engine, db_url)
    ensure_bootstrap_admin()


def get_session() -> Generator[Session, None, None]:
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    factory = _SessionLocal
    if factory is None:
        raise RuntimeError("database session factory not initialized")
    db = factory()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """测试用：清空全局引擎。"""
    global _engine, _SessionLocal
    engine = _engine
    if engine is not None:
        engine.dispose()
    _engine = None
    _SessionLocal = None
    from ..artifacts.storage import reset_artifact_store
    from ..artifacts.app_build_storage import reset_app_build_store

    reset_artifact_store()
    reset_app_build_store()
    from ..identity.oidc import reset_oidc_cache

    reset_oidc_cache()
    from ..ops.runtime_config import reload_runtime_config

    reload_runtime_config()
