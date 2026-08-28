"""Android 已安装 App 全生命周期管理。"""

from __future__ import annotations

import base64
import os
import re
import shlex
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

# noinspection PyPackageRequirements
from adbutils import adb  # type: ignore[import-untyped]

_SIGNATURE_MISMATCH = re.compile(
    r"INSTALL_FAILED_UPDATE_INCOMPATIBLE.*?Existing package\s+"
    r"([A-Za-z_][A-Za-z0-9_.]*)\s+signatures",
    re.IGNORECASE | re.DOTALL,
)
_INSTALLABLE_SUFFIXES = {".apk", ".xapk"}


def _device(device_id: str) -> Any:
    return adb.device(device_id)


def _shell(device_id: str, command: str, timeout: float = 30.0) -> str:
    return str(_device(device_id).shell(command, timeout=timeout) or "")


def _parse_packages(output: str) -> list[tuple[str, str]]:
    packages: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.startswith("package:"):
            continue
        body = line[len("package:") :]
        split = body.rfind("=")
        if split > 0:
            packages.append((body[:split].strip(), body[split + 1 :].strip()))
    return packages


def _system_package_set(device_id: str) -> set[str]:
    return {
        package
        for _path, package in _parse_packages(
            _shell(device_id, "pm list packages -f -s")
        )
    }


def _batch_version_names(
    device_id: str,
    package_names: list[str],
    *,
    timeout: float = 25.0,
) -> dict[str, str]:
    """从 dumpsys 批量解析 versionName；大包列表跳过以保证 app.list 及时返回。"""
    if not package_names or len(package_names) > 120:
        return {}
    wanted = set(package_names)
    try:
        output = _shell(device_id, "dumpsys package packages", timeout=timeout)
    except (OSError, RuntimeError):
        return {}
    versions: dict[str, str] = {}
    current: str | None = None
    for line in output.splitlines():
        pkg_match = re.match(r"\s*Package \[([^]]+)]", line)
        if pkg_match:
            pkg = pkg_match.group(1).strip()
            current = pkg if pkg in wanted else None
            continue
        if not current:
            continue
        version_match = re.match(r"\s*versionName=(.+)$", line)
        if version_match:
            versions[current] = version_match.group(1).strip()
            current = None
            if len(versions) >= len(wanted):
                break
    return versions


def list_packages(device_id: str, scope: str = "all") -> dict[str, Any]:
    if scope not in {"all", "third_party", "system"}:
        raise ValueError("scope 须为 all | third_party | system")
    flag = "-3" if scope == "third_party" else "-s" if scope == "system" else ""
    packages = _parse_packages(_shell(device_id, f"pm list packages -f {flag}".strip()))
    if scope == "system":
        system_packages: set[str] | None = None
        filtered = packages
    else:
        system_packages = _system_package_set(device_id)
        if scope == "third_party":
            filtered = [(path, pkg) for path, pkg in packages if pkg not in system_packages]
        else:
            filtered = packages
    package_names = [pkg for _path, pkg in filtered]
    version_names = _batch_version_names(device_id, package_names)
    result = []
    for apk_path, package in filtered:
        is_system = True if scope == "system" else package in (system_packages or set())
        result.append(
            {
                "package": package,
                "apk_path": apk_path,
                "system": is_system,
                "size": 0,
                "version_name": version_names.get(package, ""),
            }
        )
    result.sort(key=lambda item: (item["system"], item["package"].lower()))
    return {"ok": True, "packages": result, "count": len(result), "scope": scope}


def package_info(device_id: str, package: str) -> dict[str, Any]:
    if not package or "/" in package or " " in package:
        raise ValueError("非法 package")
    output = _shell(device_id, f"dumpsys package {shlex.quote(package)}")
    version_name = re.search(r"^\s*versionName=(.+)$", output, re.MULTILINE)
    version_code = re.search(r"^\s*versionCode=(\d+)", output, re.MULTILINE)
    return {
        "package": package,
        "version_name": version_name.group(1).strip() if version_name else "",
        "version_code": int(version_code.group(1)) if version_code else 0,
    }


def uninstall(device_id: str, package: str, keep_data: bool = False) -> dict[str, Any]:
    flag = "-k " if keep_data else ""
    output = _shell(
        device_id,
        f"pm uninstall {flag}{shlex.quote(package)}",
        120,
    )
    if "Success" not in output:
        raise RuntimeError(output.strip() or "卸载失败")
    return {"ok": True, "action": "uninstall", "package": package}


def launch(device_id: str, package: str) -> dict[str, Any]:
    output = _shell(
        device_id,
        f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1",
    )
    if "No activities found" in output or "monkey aborted" in output.lower():
        raise RuntimeError(output.strip() or "找不到启动 Activity")
    return {"ok": True, "action": "launch", "package": package}


def stop(device_id: str, package: str) -> dict[str, Any]:
    _shell(device_id, f"am force-stop {shlex.quote(package)}")
    return {"ok": True, "action": "stop", "package": package}


def is_installable_package(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in _INSTALLABLE_SUFFIXES


def extract_xapk_apks(xapk_path: str, temp_dir: str) -> list[str]:
    """解压 XAPK（zip），收集其中全部 .apk 路径（含子目录）。"""
    extract_dir = os.path.join(temp_dir, Path(xapk_path).stem or "xapk")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(xapk_path, "r") as archive:
        archive.extractall(extract_dir)
    apk_paths: list[str] = []
    for root, _dirs, files in os.walk(extract_dir):
        for name in files:
            if name.lower().endswith(".apk"):
                apk_paths.append(os.path.join(root, name))
    apk_paths.sort()
    if not apk_paths:
        raise ValueError("XAPK 中未包含 APK 文件")
    return apk_paths


def _adb_executable() -> str:
    return str(adb.adb_path())


def _install_local_paths(device_id: str, local_paths: list[str]) -> str:
    """在本机路径上执行 adb install / install-multiple（参考 WebAppForAndroid）。"""
    if not local_paths:
        raise ValueError("缺少待安装 APK")
    adb_path = _adb_executable()
    if len(local_paths) == 1:
        command = [adb_path, "-s", device_id, "install", "-r", "-t", local_paths[0]]
    else:
        command = [
            adb_path,
            "-s",
            device_id,
            "install-multiple",
            "-r",
            "-t",
            *local_paths,
        ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(output or f"adb 安装失败 exit {completed.returncode}")
    return output


def _install_result_from_output(
    output: str,
    *,
    filename: str,
    split_count: int = 1,
    force_replace: bool = False,
    device_id: str = "",
    retry_paths: list[str] | None = None,
) -> dict[str, Any]:
    if "Success" in output:
        payload: dict[str, Any] = {
            "ok": True,
            "action": "install",
            "filename": filename,
        }
        if split_count > 1:
            payload["split_count"] = split_count
        return payload
    mismatch = _SIGNATURE_MISMATCH.search(output)
    if mismatch and force_replace and device_id and retry_paths:
        package = mismatch.group(1)
        uninstall(device_id, package)
        retry_output = _install_local_paths(device_id, retry_paths)
        return _install_result_from_output(
            retry_output,
            filename=filename,
            split_count=split_count,
            force_replace=False,
            device_id=device_id,
            retry_paths=None,
        )
    if mismatch:
        return {
            "ok": False,
            "error_code": "signature_mismatch",
            "existing_package": mismatch.group(1),
            "error": output,
        }
    return {"ok": False, "error": output or "安装失败"}


def install_local_apk(
    device_id: str,
    local_path: str,
    *,
    force_replace: bool = False,
) -> dict[str, Any]:
    basename = os.path.basename(local_path) or "app.apk"
    suffix = Path(basename).suffix.lower()
    if suffix not in _INSTALLABLE_SUFFIXES:
        return {"ok": False, "error": "仅支持 .apk / .xapk 安装"}

    try:
        if suffix == ".xapk":
            with tempfile.TemporaryDirectory(prefix="autopilot_xapk_") as temp_dir:
                apk_paths = extract_xapk_apks(local_path, temp_dir)
                output = _install_local_paths(device_id, apk_paths)
                return _install_result_from_output(
                    output,
                    filename=basename,
                    split_count=len(apk_paths),
                    force_replace=force_replace,
                    device_id=device_id,
                    retry_paths=apk_paths,
                )
        output = _install_local_paths(device_id, [local_path])
        return _install_result_from_output(
            output,
            filename=basename,
            force_replace=force_replace,
            device_id=device_id,
            retry_paths=[local_path],
        )
    except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def export_apk(device_id: str, package: str) -> dict[str, Any]:
    output = _shell(device_id, f"pm path {shlex.quote(package)}")
    paths = [
        line.split("package:", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("package:")
    ]
    if not paths:
        raise FileNotFoundError(package)
    data = bytes(_device(device_id).sync.read_bytes(paths[0]))
    chunk_size = 48 * 1024
    chunks = [
        base64.b64encode(data[offset : offset + chunk_size]).decode("ascii")
        for offset in range(0, len(data), chunk_size)
    ]
    return {
        "ok": True,
        "package": package,
        "filename": f"{package}.apk",
        "size": len(data),
        "chunks": chunks,
    }
