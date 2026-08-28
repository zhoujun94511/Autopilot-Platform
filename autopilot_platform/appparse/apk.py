"""APK 信息解析。

首选纯 Python 的 pyaxmlparser（跨平台、零二进制依赖）解析 AndroidManifest.xml；
当 pyaxmlparser 不可用或解析失败时，回退到内置 aapt（resources/re_aapt 按平台自举）。
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApkInfo:
    package: str
    main_activity: str
    version_name: str = ""
    version_code: str = ""
    app_name: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    max_sdk: str = ""
    permissions: list = field(default_factory=list)
    native_abis: list = field(default_factory=list)
    signing: str = ""                   # 签名摘要：未签名 / 已签名（v1、v2…）
    file_md5: str = ""
    file_size_byte: int = 0

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size_byte / (1024 * 1024), 2)

    @staticmethod
    def display(value, empty: str = "—") -> str:
        if value is None or value == "" or value == []:
            return empty
        if isinstance(value, (list, tuple)):
            return "，".join(str(x) for x in value)
        return str(value)


def parse_apk(apk_path: str) -> ApkInfo:
    if not os.path.exists(apk_path):
        from .errors import PackageError
        raise PackageError(f"APK 文件不存在: {apk_path}")
    # 首选 pyaxmlparser；不可用或异常时回退 aapt
    import logging
    logging.getLogger("pyaxmlparser").setLevel(logging.ERROR)
    # noinspection PyBroadException
    try:
        # noinspection PyUnresolvedReferences
        from pyaxmlparser import APK
        apk = APK(apk_path)
        info = ApkInfo(
            package=apk.package or "",
            main_activity=apk.get_main_activity() or "",
            version_name=str(apk.version_name or ""),
            version_code=str(apk.version_code or ""),
            app_name=str(apk.application or ""),
            min_sdk=_apk_call(apk, "get_min_sdk_version"),
            target_sdk=_apk_call(apk, "get_target_sdk_version"),
            max_sdk=_apk_call(apk, "get_max_sdk_version"),
            permissions=_apk_permissions(apk),
            signing=_apk_signing(apk),
        )
    except Exception:
        info = _parse_via_aapt(apk_path)
        if info is None:
            from .errors import PackageError
            raise PackageError(
                "APK 解析失败：未安装 pyaxmlparser 且内置 aapt 不可用。"
                "请 pip install pyaxmlparser 或确认 resources/re_aapt 存在对应平台 aapt。")
    if not info.native_abis:
        info.native_abis = _native_abis_from_zip(apk_path)
    _fill_file_meta(info, apk_path)
    return info


def _apk_call(apk, method: str, default: str = "") -> str:
    fn = getattr(apk, method, None)
    if not callable(fn):
        return default
    # noinspection PyBroadException
    try:
        v = fn()
        return str(v) if v not in (None, "") else default
    except Exception:
        return default


def _permission_names(value: object | None) -> list[str]:
    """把 permissions 返回值规范为字符串列表（调用方负责先解开 callable）。"""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return sorted({str(p) for p in value})
    return [str(value)]


def _apk_permissions(apk) -> list:
    # noinspection PyBroadException
    try:
        gp = getattr(apk, "get_permissions", None)
        if callable(gp):
            return _permission_names(gp())
        perm = getattr(apk, "permissions", None)
        if callable(perm):
            return _permission_names(perm())
        return _permission_names(perm)
    except Exception:
        return []


def _apk_signing(apk) -> str:
    signed = getattr(apk, "is_signed", None)
    if not callable(signed) or not signed():
        return "未签名"
    parts: list[str] = []
    for label, meth in (("v1", "is_signed_v1"), ("v2", "is_signed_v2"), ("v3", "is_signed_v3")):
        fn = getattr(apk, meth, None)
        if callable(fn) and fn():
            parts.append(label)
    return f"已签名（{'、'.join(parts)}）" if parts else "已签名"


def _native_abis_from_zip(apk_path: str) -> list:
    abis: set[str] = set()
    # noinspection PyBroadException
    try:
        with zipfile.ZipFile(apk_path) as zf:
            for name in zf.namelist():
                parts = name.replace("\\", "/").split("/")
                if len(parts) >= 2 and parts[0] == "lib" and parts[1]:
                    abis.add(parts[1])
    except Exception:
        pass
    return sorted(abis)


def _fill_file_meta(info: ApkInfo, apk_path: str) -> None:
    st = os.stat(apk_path)
    info.file_size_byte = st.st_size
    h = hashlib.md5()
    with open(apk_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    info.file_md5 = h.hexdigest()


def _parse_via_aapt(apk_path: str) -> Optional[ApkInfo]:
    """用内置 aapt 解析；不可用返回 None。"""
    from . import aapt
    badging = aapt.dump_badging(apk_path)
    if not badging.get("package"):
        return None
    return ApkInfo(
        package=badging.get("package", ""),
        main_activity=badging.get("main_activity", ""),
        version_name=badging.get("version_name", ""),
        version_code=badging.get("version_code", ""),
        app_name=badging.get("app_name", ""),
        min_sdk=badging.get("min_sdk", ""),
        target_sdk=badging.get("target_sdk", ""),
        max_sdk=badging.get("max_sdk", ""),
        permissions=badging.get("permissions", []),
        native_abis=badging.get("native_abis", []) or _native_abis_from_zip(apk_path),
    )
