"""ElasticSearch 关键字。关键字 id 见 keyword_defs 定义（参考 ElasticSearchKeyword.json）。

对标 ElasticSearchKeyword。elasticsearch 库懒加载。
"""

from __future__ import annotations

import json
import time

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


def _es(ctx: ExecutionContext, url: str):
    """创建/注入 ES 客户端。测试可替换：ctx.es_factory(url)。"""
    factory = getattr(ctx, "es_factory", None)
    if factory is not None:
        return factory(url)
    try:
        # noinspection PyPackageRequirements
        from elasticsearch import Elasticsearch
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 elasticsearch，pip install elasticsearch") from e
    return Elasticsearch(url)


@keyword("es_query_dsl", name="ES查询:QueryDSL", category="Public",
         out_params=["result_out_var"], legacy_impl="ElasticSearchKeyword:queryDsl")
def query_dsl(ctx: ExecutionContext, url="", dsl="", result_out_var="",
              **_kw) -> dict:
    """连 ES，执行 dsl（JSON 查询），结果（JSON 字符串）存入 OUT 变量。"""
    try:
        body = json.loads(dsl) if isinstance(dsl, str) else dsl
    except (ValueError, TypeError) as e:
        raise KeywordError(f"QueryDSL 语句非法 JSON: {dsl!r}") from e
    client = _es(ctx, url)
    result = client.search(body=body)
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False, default=str)
    return {result_out_var: result}


def _resolve_index(type_: str) -> str:
    """对标 EsOperate.getIndexNameForWindq：按 type 取 sendtrace/receivetrace。"""
    if type_ is None or "send" in str(type_).lower():
        return "sendtrace"
    return "receivetrace"


# noinspection PyShadowingBuiltins,PyShadowingNames,PyPep8Naming
@keyword("es_query_log", name="WindQ消息日志查询", category="Http",
         out_params=["request"], legacy_impl="ElasticSearchKeyword:queryLog")
def query_log(ctx: ExecutionContext, url="", destination="", type="SEND",
              keyword="", requestNumber="1", timeRange="30", request="",
              **_kw) -> dict:
    """按关键字/时间范围/条数查 WindQ 日志，命中报文写入 request 指定的变量。"""
    req_number = int(requestNumber)
    request_vars = [v.strip() for v in str(request).split(",")]
    if req_number != len(request_vars):
        raise KeywordError("设置的报文个数和输出变量的个数不一致!")

    index = _resolve_index(type)
    now_ms = int(time.time() * 1000)
    range_ms = int(timeRange) * 60 * 1000
    must: list[dict] = [{"range": {"timestamp": {"gte": now_ms - range_ms, "lte": now_ms}}}]
    if destination:
        must.append({"term": {"destination": destination}})
    if keyword:
        must.append({"query_string": {"query": keyword}})
    body = {"query": {"bool": {"must": must}}, "size": req_number,
            "sort": [{"timestamp": {"order": "desc"}}]}

    client = _es(ctx, url)
    result = client.search(index=index, body=body)
    if isinstance(result, str):
        result = json.loads(result)
    hits = (result or {}).get("hits", {}).get("hits", [])

    request_list = []
    seen = set()
    for h in hits:
        src = h.get("_source", h) if isinstance(h, dict) else {}
        mid = src.get("messageId")
        if mid in seen:
            continue
        seen.add(mid)
        request_list.append(src)

    out: dict = {}
    for idx, var in enumerate(request_vars):
        if idx < len(request_list):
            full = request_list[idx].get("fullTextMessage")
            out[var] = "fullTextMessage is null" if full is None else str(full)
        else:
            out[var] = "String.empty"
    return out
