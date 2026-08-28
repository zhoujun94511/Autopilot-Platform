"""API 断言关键字：状态码 / 耗时 / JSON Schema。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..context import ExecutionContext
from ..registry import KeywordError, keyword


def _last(ctx: ExecutionContext) -> dict[str, Any]:
    data = getattr(ctx, "last_http", None)
    return data if isinstance(data, dict) else {}


def _as_int(val: Any, label: str) -> int:
    try:
        return int(val)
    except (TypeError, ValueError) as exc:
        raise KeywordError(f"{label} 不是整数: {val!r}") from exc


def _parse_status_spec(expected: str) -> tuple[int, int] | set[int] | int:
    """支持 '200' | '200-299' | '200,201,204'。"""
    s = str(expected or "").strip()
    if not s:
        raise KeywordError("http_assert_status: expected 不能为空")
    if "-" in s and "," not in s:
        a, _, b = s.partition("-")
        return _as_int(a.strip(), "status min"), _as_int(b.strip(), "status max")
    if "," in s:
        return {_as_int(p.strip(), "status") for p in s.split(",") if p.strip()}
    return _as_int(s, "status")


@keyword("http_assert_status", name="断言HTTP状态码", category="Http")
def http_assert_status(
    ctx: ExecutionContext,
    expected: str = "200",
    status: str = "",
    **_kw: Any,
) -> dict:
    """断言最近一次请求或显式 status 变量符合 expected。"""
    if status not in (None, ""):
        actual = _as_int(status, "status")
    else:
        last = _last(ctx)
        if "status" not in last:
            raise KeywordError("http_assert_status: 无最近 HTTP 响应，请先发请求或传入 status")
        actual = _as_int(last["status"], "status")
    spec = _parse_status_spec(expected)
    if isinstance(spec, tuple):
        lo, hi = spec
        ok = lo <= actual <= hi
        detail = f"{lo}-{hi}"
    elif isinstance(spec, set):
        ok = actual in spec
        detail = ",".join(str(x) for x in sorted(spec))
    else:
        ok = actual == spec
        detail = str(spec)
    if not ok:
        raise KeywordError(f"HTTP 状态码断言失败: 实际={actual}, 期望={detail}")
    return {}


@keyword("http_assert_time_lt", name="断言响应时间小于", category="Http")
def http_assert_time_lt(
    ctx: ExecutionContext,
    max_ms: str = "3000",
    response_time: str = "",
    **_kw: Any,
) -> dict:
    limit = _as_int(max_ms, "max_ms")
    if response_time not in (None, ""):
        actual = _as_int(response_time, "response_time")
    else:
        last = _last(ctx)
        if "elapsed_ms" not in last:
            raise KeywordError("http_assert_time_lt: 无最近响应时间，请先发请求或传入 response_time")
        actual = _as_int(last["elapsed_ms"], "response_time")
    if actual >= limit:
        raise KeywordError(f"响应时间断言失败: 实际={actual}ms, 上限={limit}ms")
    return {}


def _load_schema(ctx: ExecutionContext, schema: str) -> Any:
    if isinstance(schema, (dict, list)):
        return schema
    text = str(schema or "").strip()
    if not text:
        raise KeywordError("json_assert_schema: schema 不能为空")
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise KeywordError(f"schema JSON 无法解析: {exc}") from exc
    # 文件路径（相对工程）
    path = Path(text)
    if not path.is_file():
        proj = getattr(ctx, "project_path", None)
        if proj:
            path = Path(proj) / text
    if not path.is_file():
        raise KeywordError(f"schema 文件不存在: {text}")
    return json.loads(path.read_text(encoding="utf-8"))


@keyword("json_assert_schema", name="断言JSON Schema", category="Http")
def json_assert_schema(
    ctx: ExecutionContext,
    json_text: str = "",
    schema: str = "",
    **_kw: Any,
) -> dict:
    """用 JSON Schema 校验报文；依赖可选包 jsonschema。"""
    try:
        # noinspection PyPackageRequirements
        import jsonschema  # 延迟：主依赖已列；未装时关键字给出明确提示
    except ImportError as exc:
        raise KeywordError(
            "json_assert_schema 需要安装 jsonschema：pip install jsonschema"
        ) from exc

    body = json_text
    if body in (None, ""):
        body = _last(ctx).get("body", "")
    if isinstance(body, (dict, list)):
        instance = body
    else:
        try:
            instance = json.loads(str(body))
        except json.JSONDecodeError as exc:
            raise KeywordError(f"响应不是合法 JSON: {exc}") from exc
    schema_obj = _load_schema(ctx, schema)
    try:
        jsonschema.validate(instance=instance, schema=schema_obj)
    except jsonschema.ValidationError as exc:
        raise KeywordError(f"JSON Schema 校验失败: {exc.message}") from exc
    return {}


@keyword("http_assert_body_contains", name="断言响应体包含", category="Http")
def http_assert_body_contains(
    ctx: ExecutionContext,
    text: str = "",
    body: str = "",
    matched: str = "true",
    mode: str = "模糊匹配",
    **_kw: Any,
) -> dict:
    """断言响应体包含/精确/正则匹配。"""
    actual = str(body if body not in (None, "") else _last(ctx).get("body", ""))
    expect = str(text or "")
    mode_s = str(mode or "")
    if "正则" in mode_s:
        is_matched = re.search(expect, actual) is not None
    elif "精确" in mode_s:
        is_matched = actual == expect
    else:
        is_matched = expect in actual
    want = str(matched).lower() != "false"
    if is_matched != want:
        raise KeywordError(
            f"响应体断言失败({mode_s}): 期望匹配={want}, 片段=[{expect[:80]}]"
        )
    return {}
