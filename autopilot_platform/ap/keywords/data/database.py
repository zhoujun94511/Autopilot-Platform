"""数据库关键字。关键字 id 见 keyword_defs 定义（参考 align-data-keywords.md）。

type=sqlite → 内置 sqlite3（可真实跑）；其它 → SQLAlchemy 懒加载（可选依赖）。
查询结果集存入 data_set 变量（list[dict]），getData/getRowCount 从该变量取。

注：database_open 的 type 形参沿用参数 id（与内置同名），已标注抑制 shadow 检查。
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


class _SqliteConn:
    def __init__(self, url: str) -> None:
        self.conn = sqlite3.connect(url)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str) -> list[dict]:
        cur = self.conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def execute(self, sql: str) -> None:
        self.conn.execute(sql)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class _SqlAlchemyConn:
    def __init__(self, url: str, username: str = "", password: str = "") -> None:
        try:
            # noinspection PyUnresolvedReferences,PyPackageRequirements
            from sqlalchemy import create_engine, text
            # noinspection PyUnresolvedReferences,PyPackageRequirements
            from sqlalchemy.engine import make_url
        except ImportError as e:  # pragma: no cover
            raise KeywordError(
                "未安装 SQLAlchemy，无法连接非 sqlite 数据库。pip install SQLAlchemy"
            ) from e
        # 把单独传入的用户名/口令并入连接 URL（驱动无关，由 SQLAlchemy URL 处理）
        u = make_url(url)
        if username:
            u = u.set(username=username)
        if password:
            u = u.set(password=password)
        self.engine = create_engine(u)
        self.conn = self.engine.connect()
        self._text = text

    def query(self, sql: str) -> list[dict]:
        result = self.conn.execute(self._text(sql))
        # noinspection PyProtectedMember
        return [dict(r._mapping) for r in result]

    def execute(self, sql: str) -> None:
        self.conn.execute(self._text(sql))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _manager(ctx: ExecutionContext) -> dict:
    mgr = getattr(ctx, "db", None)
    if mgr is None:
        mgr = {}
        ctx.db = mgr  # type: ignore[attr-defined]
    return mgr


# noinspection PyShadowingBuiltins
@keyword("database_open", name="打开数据库连接", category="Public",
         legacy_impl="DatabaseKeyword:open")
def database_open(ctx: ExecutionContext, alias="", type="sqlite", url="",
                  username="", password="", **_kw) -> None:
    t = (type or "sqlite").lower()
    if t == "sqlite":
        conn: Any = _SqliteConn(url or ":memory:")
    else:
        conn = _SqlAlchemyConn(url, username, password)
    _manager(ctx)[alias or ""] = conn


def _conn(ctx: ExecutionContext, alias: str):
    conn = _manager(ctx).get(alias or "")
    if conn is None:
        raise KeywordError(f"数据库未连接（alias={alias!r}），请先 database_open")
    return conn


# noinspection PyPep8Naming
@keyword("database_query", name="执行查询SQL", category="Public",
         out_params=["data_set"], legacy_impl="DatabaseKeyword:query")
def database_query(ctx: ExecutionContext, alias="", sql="", data_set="",
                   maxTimeOut="", **_kw) -> dict:
    # maxTimeOut(秒)：结果为空时按 1s 间隔轮询重试直到有数据或超时（应对入库延迟）；空/0 只查一次
    conn = _conn(ctx, alias)
    try:
        wait_s = float(maxTimeOut) if str(maxTimeOut).strip() else 0
    except (TypeError, ValueError):
        wait_s = 0
    rows = conn.query(sql)
    if not rows and wait_s > 0:
        import time
        deadline = time.monotonic() + wait_s
        while not rows and time.monotonic() < deadline:
            time.sleep(1)
            rows = conn.query(sql)
    return {data_set: rows}


@keyword("database_non_query", name="执行非查询SQL", category="Public",
         legacy_impl="DatabaseKeyword:executeNonResultSql")
def database_non_query(ctx: ExecutionContext, alias="", sql="", **_kw) -> None:
    _conn(ctx, alias).execute(sql)


@keyword("database_get_data", name="获取结果集数据", category="Public",
         out_params=["value"], legacy_impl="DatabaseKeyword:getData")
def database_get_data(ctx: ExecutionContext, data_set="", row="0", column="0",
                      value="", **_kw) -> dict:
    rows = ctx.get_var(data_set) or []
    try:
        r = rows[int(row)]
    except (IndexError, ValueError):
        raise KeywordError(f"结果集行越界: row={row}")
    if isinstance(r, dict):
        keys = list(r.keys())
        col = r.get(column) if column in r else (
            r.get(keys[int(column)]) if str(column).isdigit() and int(column) < len(keys) else None)
    else:
        col = r[int(column)]
    return {value: "" if col is None else col}


@keyword("database_get_rowcount", name="获取结果集行数", category="Public",
         out_params=["value"], legacy_impl="DatabaseKeyword:getRowCount")
def database_get_rowcount(ctx: ExecutionContext, data_set="", value="", **_kw) -> dict:
    rows = ctx.get_var(data_set) or []
    return {value: len(rows)}


@keyword("database_close", name="关闭数据库连接", category="Public",
         legacy_impl="DatabaseKeyword:close")
def database_close(ctx: ExecutionContext, alias="", **_kw) -> None:
    mgr = _manager(ctx)
    conn: Any = mgr.pop(alias or "", None)
    if conn is not None:
        conn.close()


# ------------------------- DatabaseKeyword 扩展关键字 -------------------------
# Hive 只是 SQL 方言，本层方言无关：直接复用上方的 _conn 连接执行。


def _cell(rows: list, row, column):
    """从结果集 list[dict]/list[tuple] 取 row/column 的单元值。"""
    try:
        r = rows[int(row)]
    except (IndexError, ValueError):
        raise KeywordError(f"结果集行越界: row={row}")
    if isinstance(r, dict):
        keys = list(r.keys())
        if column in r:
            return r.get(column)
        if str(column).isdigit() and int(column) < len(keys):
            return r.get(keys[int(column)])
        raise KeywordError(f"结果集列不存在: column={column}")
    return r[int(column)]


def _verify_match(actual: str, text: str, mode: str, matched: bool) -> bool:
    m = (mode or "").strip()
    if m in ("正则表达式匹配", "正则匹配", "正则"):
        ok = re.search(text, actual) is not None
    elif m in ("模糊匹配", "包含"):
        ok = text in actual
    else:  # 精确匹配
        ok = actual == text
    return ok == matched


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "是", "yes")


@keyword("database_non_query_FromFile", name="批量执行SQL", category="Public",
         legacy_impl="DatabaseKeyword:executeNonResultSqlFromFile")
def database_non_query_from_file(ctx: ExecutionContext, alias="", path="", **_kw) -> None:
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    _conn(ctx, alias).execute(sql)


@keyword("database_executeNoneQueSQL_HIVE", name="执行非查询SQL(Hive)", category="Public",
         legacy_impl="DatabaseKeyword:executeNonQueSqlForHive")
def database_execute_none_que_sql_hive(ctx: ExecutionContext, alias="", sql="", **_kw) -> None:
    _conn(ctx, alias).execute(sql)


# noinspection PyPep8Naming
@keyword("database_executeQueSQL_HIVE", name="执行查询SQL并获取结果内容(Hive)", category="Public",
         out_params=["value"], legacy_impl="DatabaseKeyword:executeSqlForHive")
def database_execute_que_sql_hive(ctx: ExecutionContext, alias="", sql="", rowIndex="0",
                                  colName="0", value="", **_kw) -> dict:
    rows = _conn(ctx, alias).query(sql)
    cell = _cell(rows, rowIndex, colName)
    return {value: "" if cell is None else cell}


# noinspection PyPep8Naming
@keyword("database_executeQueSQL_GETCOUNT_HIVE", name="执行查询SQL并获取行数(Hive)", category="Public",
         out_params=["rowCount"], legacy_impl="DatabaseKeyword:executeSqlAndGetCountForHive")
def database_execute_que_sql_getcount_hive(ctx: ExecutionContext, alias="", sql="",
                                           rowCount="", **_kw) -> dict:
    rows = _conn(ctx, alias).query(sql)
    return {rowCount: len(rows)}


@keyword("database_verify_data", name="校验数据库结果集", category="Public",
         legacy_impl="DatabaseKeyword:verifyData")
def database_verify_data(ctx: ExecutionContext, data_set="", row="0", column="0",
                         text="", matched="true", mode="精确匹配", **_kw) -> None:
    rows = ctx.get_var(data_set) or []
    cell = _cell(rows, row, column)
    actual = "" if cell is None else str(cell)
    want = _as_bool(matched)
    if not _verify_match(actual, text, mode, want):
        raise KeywordError(
            f"校验数据库结果集失败: 实际值={actual!r} 期望{'匹配' if want else '不匹配'} "
            f"{text!r}（模式={mode}）"
        )


_ROWCOUNT_OPS = {
    "大于": lambda a, b: a > b,
    "等于": lambda a, b: a == b,
    "小于": lambda a, b: a < b,
    "不等于": lambda a, b: a != b,
    "大于等于": lambda a, b: a >= b,
    "小于等于": lambda a, b: a <= b,
}


# noinspection PyPep8Naming
@keyword("database_verify_rowCount", name="校验数据库结果行数", category="Public",
         legacy_impl="DatabaseKeyword:verifyRowCount")
def database_verify_row_count(ctx: ExecutionContext, data_set="", mode="等于",
                              rowCount_exp="0", **_kw) -> None:
    rows = ctx.get_var(data_set) or []
    actual = len(rows)
    try:
        exp = int(rowCount_exp)
    except (TypeError, ValueError):
        raise KeywordError(f"期望行数非法: rowCount_exp={rowCount_exp!r}")
    op = _ROWCOUNT_OPS.get((mode or "").strip())
    if op is None:
        raise KeywordError(f"不支持的比较模式: {mode!r}")
    if not op(actual, exp):
        raise KeywordError(f"校验数据库结果行数失败: 实际={actual} 期望{mode}{exp}")
