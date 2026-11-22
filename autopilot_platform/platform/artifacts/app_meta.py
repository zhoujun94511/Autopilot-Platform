"""应用包元数据解析（完整 appparse，不依赖外部 autopilot 包）。"""

from __future__ import annotations

from pathlib import Path

from autopilot_platform.appparse import PackageError, parse_apk, parse_ipa


def _version_code_int(raw: str | int | None) -> int:
    try:
        return int(str(raw or "0") or 0)
    except (TypeError, ValueError):
        return 0


def parse_ipa_meta(path: str | Path) -> tuple[str, str, str, int]:
    """返回 (bundle_id, main_activity_unused, version_name, version_code)。"""
    try:
        info = parse_ipa(str(path))
    except PackageError:
        return "", "", "", 0
    return (
        info.bundle_id or "",
        "",
        info.version_name or "",
        _version_code_int(info.version_code),
    )


def parse_apk_meta(path: str | Path) -> tuple[str, str, str, int]:
    """返回 (package, main_activity, version_name, version_code)。"""
    try:
        info = parse_apk(str(path))
    except PackageError:
        return "", "", "", 0
    return (
        info.package or "",
        info.main_activity or "",
        info.version_name or "",
        _version_code_int(info.version_code),
    )
