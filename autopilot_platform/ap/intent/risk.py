"""Intent 调用风险分级（roadmap B2）。

风险在执行层强制，不依赖 Prompt。合并关键字元数据 / REGISTRY.risk_level
与硬编码兜底集合，取更高风险（irreversible > write > read），避免 XML
误标为 write/read 时绕过已知高危关键字（AUD-P2-010）。
默认拒绝 irreversible 经 Intent 调用；
可用 ``AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE=1`` 放行（仅调试）。

注意：与 Design Chat 的设计侧 risk_level（high/medium）不是同一概念。
"""

from __future__ import annotations

import os
from typing import Any, Literal

from ..keywords.registry import REGISTRY, KeywordError
from ..metadata.keyword_meta import load_catalog

RiskLevel = Literal["read", "write", "irreversible"]

# 明确不可逆 / 高危（Intent / Vision 默认禁止）；与 XML 取 max，不可被降级
_IRREVERSIBLE: frozenset[str] = frozenset(
    {
        "mobile_app_adb_uninstall",
        "mobile_app_uninstall",
        # 含 am force-stop / 随机破坏性操作（AUD-2026-09）
        "mobile_app_reset_saveinfo",
        "mobile_monkey",
        "web_browser_deleteAllCookies",
        # Redis（legacy implement 名 + XML keyword id）
        "deleteRedisKey",
        "deleteRedisKeyWithResult",
        "deleteRedisScoredSet",
        "deleteRedisKeyFromFile",
        "redis_del_RedisKey",
        "redis_del_RedisKey_withResult",
        "redis_del_RedisScoredSet",
        "redis_del_RedisKeyFromFile",
        "http_delete",
        "json_delete_json_value",
        # SSH 远程命令 / 文件传输（连接本身仍为 write；AUD-2026-09）
        "linux_ssh_runCmd_WithResult",
        "linux_ssh_runCmd_WithoutResult",
        "linux_ssh_sftp_fileUpload",
        "linux_ssh_sftp_fileDownload",
    }
)

_READ_MARKERS = (
    "get_",
    "verify_",
    "assert_",
    "check_",
    "find_",
    "wait_",
    "screenshot",
    "capture",
    "list_",
    "read_",
    "http_get",
)

_VALID = frozenset({"read", "write", "irreversible"})
_RANK: dict[str, int] = {"read": 0, "write": 1, "irreversible": 2}


def _max_level(*levels: RiskLevel | None) -> RiskLevel | None:
    best: RiskLevel | None = None
    best_r = -1
    for lv in levels:
        if lv is None or lv not in _RANK:
            continue
        r = _RANK[lv]
        if r > best_r:
            best, best_r = lv, r
    return best


def _from_registry(keyword_id: str) -> RiskLevel | None:
    try:

        kd = REGISTRY.get(keyword_id)
        lv = (getattr(kd, "risk_level", None) or "").strip().lower() if kd else ""
        if lv in _VALID:
            return lv  # type: ignore[return-value]
    except (ImportError, AttributeError, TypeError):
        pass
    return None


def _from_catalog(keyword_id: str) -> RiskLevel | None:
    try:

        meta = load_catalog().get(keyword_id)
        lv = (getattr(meta, "risk_level", None) or "").strip().lower() if meta else ""
        if lv in _VALID:
            return lv  # type: ignore[return-value]
    except (ImportError, OSError, RuntimeError, TypeError, AttributeError, ValueError):
        pass
    return None


def risk_level(keyword_id: str) -> RiskLevel:
    kid = (keyword_id or "").strip()
    if not kid:
        return "write"
    meta: RiskLevel | None = None
    for getter in (_from_registry, _from_catalog):
        found = getter(kid)
        if found is not None:
            meta = found
            break
    hard: RiskLevel | None = "irreversible" if kid in _IRREVERSIBLE else None
    merged = _max_level(meta, hard)
    if merged is not None:
        return merged
    low = kid.lower()
    if any(m in low for m in _READ_MARKERS):
        return "read"
    return "write"


def allow_irreversible() -> bool:
    raw = (os.environ.get("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def assert_intent_keyword_allowed(keyword_id: str, *, source: str = "intent") -> None:
    """Intent 路径调用前检查；不可逆且未放行则抛 KeywordError 兼容异常。"""
    level = risk_level(keyword_id)
    if level != "irreversible":
        return
    if allow_irreversible():
        return

    raise KeywordError(
        f"Intent 拒绝调用高风险关键字 {keyword_id} "
        f"(risk=irreversible, source={source})；"
        f"设置 AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE=1 可临时放行"
    )


def filter_safe_candidates(
    cands: list[dict[str, Any]] | None,
    *,
    blocked_out: list[str] | None = None,
) -> list[dict[str, Any]]:
    """从 resolve/Vision 候选中去掉 irreversible（未放行时）。

    ``blocked_out``：收集被拒的关键字 id，供上层把「候选为空」区分为
    「解析不出来」还是「被风险闸门拦掉」，否则用户只会看到含糊的解析失败。
    """
    items = list(cands or [])
    if allow_irreversible():
        return items
    out: list[dict[str, Any]] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        kid = str(c.get("keyword_id") or c.get("keyword") or "").strip()
        if kid and risk_level(kid) == "irreversible":
            if blocked_out is not None and kid not in blocked_out:
                blocked_out.append(kid)
            continue
        out.append(c)
    return out
