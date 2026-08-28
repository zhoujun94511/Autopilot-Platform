"""HBase 关键字。关键字 id 见 keyword_defs 定义（参考 HbaseKeyword.json）。happybase 库懒加载。"""

from __future__ import annotations

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


def _manager(ctx: ExecutionContext) -> dict:
    mgr = getattr(ctx, "hbase", None)
    if mgr is None:
        mgr = {}
        ctx.hbase = mgr  # type: ignore[attr-defined]
    return mgr


# noinspection PyPep8Naming,PyUnusedLocal
def default_hbase_factory(quorum: str, clientPort: str, hadoopUser: str,
                          hadoopGroup: str):
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        import happybase
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 happybase，pip install happybase") from e
    return happybase.Connection(host=quorum, port=int(clientPort))


# 测试可替换：ctx.hbase_factory
def _factory(ctx: ExecutionContext):
    return getattr(ctx, "hbase_factory", None) or default_hbase_factory


# noinspection PyPep8Naming
@keyword("hbase_connect", name="配置HBase数据库连接", category="Public",
         legacy_impl="HbaseKeyword:connectHbase")
def hbase_connect(ctx: ExecutionContext, alias="", quorum="", clientPort="",
                  hadoopUser="", hadoopGroup="", **_kw) -> None:
    conn = _factory(ctx)(quorum, clientPort, hadoopUser, hadoopGroup)
    _manager(ctx)[alias or ""] = conn


def _connection(ctx: ExecutionContext, alias: str):
    c = _manager(ctx).get(alias or "")
    if c is None:
        raise KeywordError(f"HBase 未连接（alias={alias!r}），请先 hbase_connect")
    return c


def _to_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


# noinspection PyPep8Naming
@keyword("hbase_verify_table_existed", name="校验HBase中表是否存在",
         category="Public", legacy_impl="HbaseKeyword:verifyTableExisted")
def verify_table_existed(ctx: ExecutionContext, alias="", tableName="",
                         isExist="true", **_kw) -> None:
    conn = _connection(ctx, alias)
    tables = conn.tables()
    names = {t.decode() if isinstance(t, bytes) else t for t in tables}
    actual = tableName in names
    expect = _to_bool(isExist)
    if actual != expect:
        raise KeywordError(
            f"HBase 表 {tableName!r} 存在性校验失败：期望存在={expect}，实际存在={actual}")


# noinspection PyPep8Naming
@keyword("hbase_get", name="执行HBase单行查询操作", category="Public",
         out_params=["outResult"], legacy_impl="HbaseKeyword:getRow")
def get_row(ctx: ExecutionContext, alias="", tableName="", rowKey="",
            outResult="", **_kw) -> dict:
    conn = _connection(ctx, alias)
    table = conn.table(tableName)
    result = table.row(rowKey)
    return {outResult: result}


# noinspection PyPep8Naming
@keyword("hbase_put", name="执行HBase单行新增操作", category="Public",
         legacy_impl="HbaseKeyword:putRow")
def put_row(ctx: ExecutionContext, alias="", tableName="", rowKey="",
            columnFamily="", column="", value="", **_kw) -> None:
    conn = _connection(ctx, alias)
    table = conn.table(tableName)
    table.put(rowKey, {f"{columnFamily}:{column}": value})


# noinspection PyPep8Naming
@keyword("hbase_del", name="执行HBase单行删除操作", category="Public",
         legacy_impl="HbaseKeyword:delRow")
def del_row(ctx: ExecutionContext, alias="", tableName="", rowKey="",
            **_kw) -> None:
    conn = _connection(ctx, alias)
    table = conn.table(tableName)
    table.delete(rowKey)


def _cell_value(result_data, column_family: str, column: str):
    key = f"{column_family}:{column}"
    if not isinstance(result_data, dict):
        return None, False
    for k, v in result_data.items():
        kk = k.decode() if isinstance(k, bytes) else k
        if kk == key:
            return v, True
    return None, False


# noinspection PyPep8Naming
@keyword("hbase_verify_cell_existed", name="校验HBase单行查询结果",
         category="Public", legacy_impl="HbaseKeyword:verifyCellExisted")
def verify_cell_existed(_ctx: ExecutionContext, resultData=None, columnFamily="",
                        column="", value="", isExist="true", **_kw) -> None:
    cell, found = _cell_value(resultData, columnFamily, column)
    expect = _to_bool(isExist)
    key = f"{columnFamily}:{column}"
    if expect:
        if not found:
            raise KeywordError(f"HBase 单元格 {key!r} 不存在，但期望存在")
        if value != "":
            actual = cell.decode() if isinstance(cell, bytes) else cell
            if str(actual) != str(value):
                raise KeywordError(
                    f"HBase 单元格 {key!r} 值校验失败：期望={value!r}，实际={actual!r}")
    else:
        if found:
            raise KeywordError(f"HBase 单元格 {key!r} 存在，但期望不存在")
