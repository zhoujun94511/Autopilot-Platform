"""本机 USB 设备探测（Console Runner 自有实现，不 import autopilot）。"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace

from .ios_marketing import marketing_name

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CLI_ENV_EXTRA = {
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "TERM": "dumb",
    "PYTHONIOENCODING": "utf-8",
}


@dataclass(frozen=True)
class LocalDevice:
    udid: str
    platform: str
    name: str = ""
    model: str = ""
    os_version: str = ""
    state: str = "ready"
    backends: tuple[str, ...] = ()
    health_note: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)


def _parse_adb_devices(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1].strip().lower()))
    return out


def _adb_bin() -> str | None:
    return shutil.which("adb")


def _run_adb(args: list[str], timeout: int = 30) -> str:
    exe = _adb_bin()
    if not exe:
        raise RuntimeError("adb not found on PATH")
    proc = subprocess.run([exe, *args], capture_output=True, timeout=timeout)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"adb failed: {' '.join(args)}\n{err or out}")
    return out


def list_android_udids() -> list[str]:
    return [d.udid for d in list_android_devices() if d.state == "ready"]


def list_ios_udids() -> list[str]:
    return [d.udid for d in list_ios_devices() if d.state == "ready"]


_ANDROID_CODENAME_RE = re.compile(r"^[a-z][a-z0-9._-]{2,24}$")


def _looks_like_android_codename(value: str) -> bool:
    """``ro.product.name`` 常为 y2qzcx 这类内部代号，不能当卡片标题。"""
    text = str(value or "").strip()
    return bool(text) and _ANDROID_CODENAME_RE.fullmatch(text) is not None


def android_friendly_name(brand: str, model: str, market: str, product: str) -> str:
    """优先市场名（Galaxy S20+），否则 Brand + Model（与 scrcpy 一致）。"""
    brand = str(brand or "").strip()
    model = str(model or "").strip()
    market = str(market or "").strip()
    product = str(product or "").strip()
    market_l = market.lower()
    skip_market = {
        "",
        model.lower(),
        product.lower(),
        brand.lower(),
    }
    if market_l not in skip_market and not _looks_like_android_codename(market):
        return market
    if brand and model:
        if model.lower().startswith(brand.lower()):
            return model
        return f"{brand} {model}".strip()
    return model or product or brand


def _android_props(serial: str) -> tuple[str, str, str]:
    try:
        def _prop(key: str) -> str:
            try:
                return (_run_adb(["-s", serial, "shell", "getprop", key]) or "").strip()
            except (OSError, RuntimeError, TypeError, ValueError):
                return ""

        brand = _prop("ro.product.brand")
        model = _prop("ro.product.model") or _prop("ro.product.device")
        ver = _prop("ro.build.version.release")
        market = _prop("ro.product.marketname")
        product = _prop("ro.product.name")
        name = android_friendly_name(brand, model, market, product)
        return name, model, ver
    except (OSError, RuntimeError, TypeError, ValueError):
        return "", "", ""


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", "replace")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(_CLI_ENV_EXTRA)
    return env


def _resolve_go_ios_exe() -> str | None:
    try:
        from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios
    except ImportError:
        return shutil.which("ios") or shutil.which("go-ios")
    found = resolve_go_ios()
    if found is not None:
        return str(found)
    return shutil.which("ios") or shutil.which("go-ios")


def _ios_tooling_available() -> bool:
    """本机能否枚举 / 驱动 iOS：go-ios 或 pymobiledevice3 任一即可。"""
    if _resolve_go_ios_exe():
        return True
    try:
        return importlib.util.find_spec("pymobiledevice3") is not None
    except (ImportError, ValueError):
        return False


def _host_backends() -> list[str]:
    backends: list[str] = []
    if _adb_bin():
        backends.append("android-appium")
    has_appium = bool(shutil.which("appium"))
    if platform.system().lower() == "darwin":
        backends.append("ios-wda")
        if has_appium:
            backends.append("ios-appium")
    elif _ios_tooling_available():
        # Windows/Linux 走 WDA-direct，不要求 Appium / macOS
        backends.append("ios-wda")
    return backends


def _has_web_browser() -> bool:
    """本机是否可跑 web(Selenium) 用例：显式开关优先，否则探测常见浏览器。

    MC_RUNNER_WEB=1/0 可强制开启/关闭；Selenium Manager 会自动解析对应 driver。
    """
    forced = os.environ.get("MC_RUNNER_WEB", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    names = (
        "chrome", "google-chrome", "chromium", "chromium-browser",
        "msedge", "microsoft-edge", "firefox",
    )
    if any(shutil.which(n) for n in names):
        return True
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        candidates = (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
        )
        return any(os.path.exists(c) for c in candidates)
    if sysname == "darwin":
        candidates = (
            "/Applications/Google Chrome.app",
            "/Applications/Microsoft Edge.app",
            "/Applications/Firefox.app",
        )
        return any(os.path.exists(c) for c in candidates)
    return False


def _has_playwright() -> bool:
    """本机是否可跑 web_engine=playwright：包 + Chromium 浏览器已安装。

    MC_RUNNER_WEB_PLAYWRIGHT=1/0 可强制开启/关闭 Runner 上报 web-playwright 能力。
    """
    forced = os.environ.get("MC_RUNNER_WEB_PLAYWRIGHT", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    try:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            return False
        # noinspection PyPackageRequirements
        from playwright.sync_api import sync_playwright  # type: ignore[import-untyped]

        pw = sync_playwright().start()
        try:
            exe = pw.chromium.executable_path
            return bool(exe and os.path.isfile(exe))
        finally:
            pw.stop()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _has_aiortc() -> bool:
    try:
        # noinspection PyPackageRequirements
        import aiortc  # noqa: F401  # type: ignore[import-untyped]

        return True
    except ImportError:
        return False


def probe_host_capabilities() -> tuple[list[str], list[str]]:
    backends = _host_backends()
    caps: list[str] = ["parallel", "report", "http"]
    if "android-appium" in backends:
        caps.append("android")
    if "ios-wda" in backends or "ios-appium" in backends:
        caps.append("ios")
    if _has_web_browser():
        caps.append("web")
    if _has_playwright():
        caps.append("web-playwright")
    # Android 远控需要 adb + aiortc（缺 aiortc 时声明会误导控制台入口）
    if _adb_bin() and _has_aiortc():
        caps.append("android-remote")
    if "ios-wda" in backends or "ios-appium" in backends:
        caps.append("ios-remote")
    for b in backends:
        if b not in caps:
            caps.append(b)
    return caps, backends


def list_android_devices() -> list[LocalDevice]:
    host_backends = _host_backends()
    android_backends = tuple(b for b in host_backends if b.startswith("android-"))
    if not _adb_bin():
        return []
    try:
        rows = _parse_adb_devices(_run_adb(["devices"]))
    except (OSError, RuntimeError, TypeError, ValueError):
        return []

    out: list[LocalDevice] = []
    for serial, adb_state in rows:
        if adb_state == "device":
            name, model, ver = _android_props(serial)
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=name or serial,
                    model=model or "",
                    os_version=ver,
                    state="ready",
                    backends=android_backends or ("android-appium",),
                )
            )
        elif adb_state == "unauthorized":
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=serial,
                    state="unauthorized",
                    health_note="adb unauthorized; unlock phone and allow USB debugging",
                )
            )
        else:
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=serial,
                    state="offline" if adb_state == "offline" else "error",
                    health_note=f"adb state={adb_state}",
                )
            )
    return out


def _extract_json_array(text: str) -> str:
    s = _strip_ansi(text or "").strip()
    if s.startswith("["):
        return s
    start, end = s.find("["), s.rfind("]")
    if 0 <= start < end:
        return s[start : end + 1]
    return ""


_IOS_IDENTITY_CACHE: dict[str, tuple[str, str, str]] = {}
_IOS_IDENTITY_FAIL_AT: dict[str, float] = {}
_IOS_IDENTITY_FAIL_COOLDOWN_SEC = 30.0


def reset_ios_identity_cache() -> None:
    """测试用：清空型号缓存与失败冷却。"""
    _IOS_IDENTITY_CACHE.clear()
    _IOS_IDENTITY_FAIL_AT.clear()


def _extract_json_object(text: str) -> str:
    s = _ANSI_RE.sub("", text or "").strip()
    if s.startswith("{"):
        return s
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        return s[start : end + 1]
    return ""


async def _ios_identity_via_lockdown_async(udid: str) -> tuple[str, str, str] | None:
    from pymobiledevice3.lockdown import create_using_usbmux

    async def _one(lockdown, key: str) -> str:
        getter = getattr(lockdown, "get_value", None)
        if getter is None:
            return ""
        try:
            value = getter(key=key)
        except TypeError:
            try:
                value = getter(key)
            except (TypeError, RuntimeError, ValueError, OSError):
                return ""
        except (RuntimeError, ValueError, OSError):
            return ""
        if hasattr(value, "__await__"):
            value = await value
        return str(value or "").strip()

    created = create_using_usbmux(serial=udid or None)
    if hasattr(created, "__await__"):
        created = await created
    if hasattr(created, "__aenter__"):
        async with created as ld:
            name = await _one(ld, "DeviceName")
            product_type = await _one(ld, "ProductType")
            version = await _one(ld, "ProductVersion")
    else:
        ld = created
        name = await _one(ld, "DeviceName")
        product_type = await _one(ld, "ProductType")
        version = await _one(ld, "ProductVersion")
    if not product_type:
        return None
    return name, product_type, version


def _ios_identity_via_lockdown(udid: str) -> tuple[str, str, str] | None:
    try:
        import asyncio

        return asyncio.run(_ios_identity_via_lockdown_async(udid))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _ios_identity_via_goios(udid: str) -> tuple[str, str, str] | None:
    exe = _resolve_go_ios_exe()
    if not exe or not udid:
        return None
    try:
        r = subprocess.run(
            [exe, "info", "--udid", udid],
            capture_output=True,
            timeout=15,
            env=_cli_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    blob = _extract_json_object(
        (r.stdout or b"").decode("utf-8", "replace")
        + "\n"
        + (r.stderr or b"").decode("utf-8", "replace")
    )
    if not blob:
        return None
    try:
        raw = json.loads(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    product_type = str(raw.get("ProductType") or raw.get("productType") or "").strip()
    if not product_type:
        return None
    name = str(raw.get("DeviceName") or raw.get("deviceName") or "").strip()
    version = str(raw.get("ProductVersion") or raw.get("productVersion") or "").strip()
    return name, product_type, version


def enrich_ios_device(device: LocalDevice) -> LocalDevice:
    """兜底枚举往往只有 UDID。补 ProductType → 市场型号，供看板展示。"""
    uid = (device.udid or "").strip()
    if not uid:
        return device
    cached = _IOS_IDENTITY_CACHE.get(uid)
    if cached:
        name, model, version = cached
        return replace(
            device,
            name=name or device.name,
            model=model or device.model,
            os_version=version or device.os_version,
        )
    if (device.model or "").strip():
        _IOS_IDENTITY_CACHE[uid] = (device.name, device.model, device.os_version)
        return device
    now = time.monotonic()
    if now - _IOS_IDENTITY_FAIL_AT.get(uid, 0.0) < _IOS_IDENTITY_FAIL_COOLDOWN_SEC:
        return device
    info = _ios_identity_via_lockdown(uid) or _ios_identity_via_goios(uid)
    if not info:
        _IOS_IDENTITY_FAIL_AT[uid] = now
        return device
    name, product_type, version = info
    model = marketing_name(product_type)
    if not model:
        _IOS_IDENTITY_FAIL_AT[uid] = now
        return device
    filled = replace(
        device,
        name=name or device.name,
        model=model,
        os_version=version or device.os_version,
    )
    _IOS_IDENTITY_CACHE[uid] = (filled.name, filled.model, filled.os_version)
    return filled


def _devices_from_pmd3_items(raw: object) -> list[LocalDevice]:
    out: list[LocalDevice] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        udid = str(item.get("UniqueDeviceID") or item.get("Identifier") or "").strip()
        if not udid:
            continue
        out.append(
            LocalDevice(
                udid=udid,
                platform="ios",
                name=str(item.get("DeviceName") or "iPhone"),
                model=marketing_name(str(item.get("ProductType") or "")),
                os_version=str(item.get("ProductVersion") or ""),
            )
        )
    return out


def _parse_pmd3_stdout(text: str) -> list[LocalDevice]:
    """解析 ``usbmux list``：允许日志/ANSI 包在 JSON 数组外。"""
    blob = _extract_json_array(text)
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return _devices_from_pmd3_items(raw)


def _list_ios_via_pymobiledevice3() -> list[LocalDevice]:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
            capture_output=True,
            timeout=30,
            env=_cli_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = _decode(r.stdout)
    if r.returncode != 0:
        return []
    return _parse_pmd3_stdout(out)


def _list_ios_via_usbmux_inproc() -> list[LocalDevice]:
    """同一条 usbmux 通道，不经 CLI 输出格式。"""
    try:
        from pymobiledevice3.usbmux import list_devices
    except ImportError:
        return []
    try:
        import asyncio

        res = list_devices()
        if asyncio.iscoroutine(res):
            res = asyncio.run(res)
    except (OSError, RuntimeError, TypeError, ValueError):
        return []
    out: list[LocalDevice] = []
    seen: set[str] = set()
    for item in res or []:
        udid = str(getattr(item, "serial", "") or getattr(item, "udid", "") or "").strip()
        if not udid or udid in seen:
            continue
        seen.add(udid)
        out.append(LocalDevice(udid=udid, platform="ios", name="iPhone"))
    return out


def _parse_goios_list(text: str) -> list[LocalDevice]:
    """解析 ``ios list``：JSONL deviceList / JSON 数组 / 纯 UDID 行。"""
    text = (text or "").strip()
    if not text:
        return []
    udids: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError, ValueError):
                payload = None
            raw = payload.get("deviceList") if isinstance(payload, dict) else payload
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item.strip():
                        udids.append(item.strip())
                    elif isinstance(item, dict):
                        uid = str(
                            item.get("udid")
                            or item.get("UDID")
                            or item.get("UniqueDeviceID")
                            or item.get("Identifier")
                            or ""
                        ).strip()
                        if uid:
                            udids.append(uid)
    if not udids:
        for line in text.splitlines():
            tok = line.strip().split()[0] if line.strip() else ""
            if tok and all(ch.isalnum() or ch == "-" for ch in tok) and len(tok) >= 25:
                udids.append(tok)
    seen: set[str] = set()
    out: list[LocalDevice] = []
    for uid in udids:
        if uid in seen:
            continue
        seen.add(uid)
        out.append(LocalDevice(udid=uid, platform="ios", name="iPhone"))
    return out


def _list_ios_via_goios() -> list[LocalDevice]:
    exe = _resolve_go_ios_exe()
    if not exe:
        return []
    try:
        # 禁止 text=True：Windows GBK 控制台遇到 UTF-8 中文会炸
        r = subprocess.run([exe, "list"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0 and not (r.stdout or r.stderr):
        return []
    text = (r.stdout or b"").decode("utf-8", "replace") + "\n" + (
        r.stderr or b""
    ).decode("utf-8", "replace")
    return _parse_goios_list(text)


def list_ios_devices() -> list[LocalDevice]:
    host_backends = _host_backends()
    ios_backends = tuple(b for b in host_backends if b.startswith("ios-"))
    raw = (
        _list_ios_via_pymobiledevice3()
        or _list_ios_via_usbmux_inproc()
        or _list_ios_via_goios()
    )
    out: list[LocalDevice] = []
    for d in raw:
        backends = ios_backends
        note = ""
        state = "ready"
        if not backends:
            state = "error"
            note = "no ios backend on this host (need go-ios or pymobiledevice3; Appium iOS 仅 macOS)"
        out.append(
            enrich_ios_device(
                LocalDevice(
                    udid=d.udid,
                    platform="ios",
                    name=d.name,
                    model=d.model,
                    os_version=d.os_version,
                    state=state,
                    backends=backends,
                    health_note=note,
                )
            )
        )
    return out


def list_local_devices() -> list[LocalDevice]:
    return [*list_android_devices(), *list_ios_devices()]


def format_probe_report(devices: list[LocalDevice] | None = None) -> str:
    caps, backends = probe_host_capabilities()
    devices = list_local_devices() if devices is None else devices
    lines = [
        f"host capabilities: {', '.join(caps) or '(none)'}",
        f"host backends:     {', '.join(backends) or '(none)'}",
        f"devices ({len(devices)}):",
    ]
    if not devices:
        lines.append("  (none)")
    for d in devices:
        be = ",".join(d.backends) or "-"
        extra = f" note={d.health_note}" if d.health_note else ""
        lines.append(
            f"  [{d.state}] {d.platform} {d.udid} "
            f"name={d.name or '-'} model={d.model or '-'} "
            f"os={d.os_version or '-'} backends={be}{extra}"
        )
    return "\n".join(lines)
