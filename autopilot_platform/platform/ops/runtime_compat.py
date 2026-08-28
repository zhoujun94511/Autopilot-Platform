"""执行核（ap）版本契约：与制品 required_runtime_version 对齐。"""

from __future__ import annotations

import re
from typing import Any


def ap_runtime_version() -> str:
    """Platform 内嵌执行核版本（``autopilot_platform.ap``）。"""
    try:
        from autopilot_platform.ap import __version__

        return str(__version__ or "").strip()
    except (ImportError, AttributeError, TypeError):
        return ""


def _norm_ver(raw: str) -> str:
    s = (raw or "").strip().lower()
    # 去掉 vendored / 前缀 v
    s = s.removeprefix("v")
    s = s.replace("-vendored", "").replace("+vendored", "")
    return s.strip()


def _major_minor(raw: str) -> tuple[str, str] | None:
    m = re.match(r"^(\d+)\.(\d+)", _norm_ver(raw))
    if not m:
        return None
    return m.group(1), m.group(2)


def versions_compatible(required: str, actual: str) -> bool:
    """公开契约：major.minor 一致；非空但无法解析视为不兼容。"""
    req = (required or "").strip()
    act = (actual or "").strip()
    if not req or not act:
        return True
    if _norm_ver(req) == _norm_ver(act):
        return True
    rp = _major_minor(req)
    ap = _major_minor(act)
    if rp is None or ap is None:
        return False
    return rp == ap


def check_artifact_runtime(
    *,
    required_runtime_version: str,
    enforce: bool = False,
) -> dict[str, Any]:
    """返回 {ok, required, actual, enforced, message}。"""
    actual = ap_runtime_version()
    required = (required_runtime_version or "").strip()
    ok = versions_compatible(required, actual)
    if required and not ok:
        msg = (
            f"制品 required_runtime_version={required} 与执行核 ap={actual} 不兼容"
        )
    elif required and ok:
        msg = f"runtime ok: required={required} actual={actual}"
    else:
        msg = f"runtime actual={actual} (no required pin)"
    if enforce and required and not ok:
        raise ValueError(msg)
    return {
        "ok": ok,
        "required": required,
        "actual": actual,
        "enforced": bool(enforce),
        "message": msg,
    }
