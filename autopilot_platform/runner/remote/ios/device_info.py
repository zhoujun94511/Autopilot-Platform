"""iOS 设备信息快照。

优先进程内 lockdown（对齐 AutoPilot / WebAppFlaskauto-iOS，避免再拉一次 go-ios 子进程）；
失败再回退 ``ios info``。WDA 只补 IP / 分辨率，已有分辨率则不再打 get_window_size。
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, cast

from autopilot_platform.runner.ios_marketing import marketing_name
from autopilot_platform.runner.local_devices import _extract_json_object
from .app_ops import _run

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOCKDOWN_TIMEOUT_SEC = 6.0
_GOIOS_TIMEOUT_SEC = 8


def _text(value: Any) -> str:
    if value is None or value == "" or value == {}:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_lockdown_info(raw: dict[str, Any], udid: str) -> dict[str, Any]:
    product_type = _text(raw.get("ProductType") or raw.get("productType"))
    info: dict[str, Any] = {
        "device_id": _text(raw.get("UniqueDeviceID") or raw.get("uniqueDeviceID")) or udid,
        "platform": "ios",
        "name": _text(raw.get("DeviceName") or raw.get("deviceName")),
        "product_type": product_type,
        "marketing": marketing_name(product_type) if product_type else "",
        "ios_version": _text(raw.get("ProductVersion") or raw.get("productVersion")),
        "build": _text(raw.get("BuildVersion") or raw.get("buildVersion")),
        "model_number": _text(raw.get("ModelNumber") or raw.get("modelNumber")),
        "hardware_model": _text(raw.get("HardwareModel") or raw.get("hardwareModel")),
        "cpu_arch": _text(raw.get("CPUArchitecture") or raw.get("cpuArchitecture")),
        "serial": _text(raw.get("SerialNumber") or raw.get("serialNumber")),
        "activation_state": _text(raw.get("ActivationState") or raw.get("activationState")),
        "imei": _text(raw.get("InternationalMobileEquipmentIdentity")),
        "imei2": _text(
            raw.get("InternationalMobileEquipmentIdentity2")
            or raw.get("MobileEquipmentIdentifier")
        ),
        "wifi_mac": _text(raw.get("WiFiAddress") or raw.get("wifiAddress")),
        "bt_mac": _text(raw.get("BluetoothAddress") or raw.get("bluetoothAddress")),
        "ethernet_mac": _text(raw.get("EthernetAddress")),
        "region": _text(raw.get("RegionInfo") or raw.get("regionInfo")),
        "timezone": _text(raw.get("TimeZone") or raw.get("timeZone")),
        "phone_number": _text(raw.get("PhoneNumber")),
        "device_class": _text(raw.get("DeviceClass") or raw.get("deviceClass")),
        "connection_type": "usb",
    }
    return {key: value for key, value in info.items() if value not in ("", None)}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await cast(Awaitable[Any], value)
    return value


async def _read_all_values(lockdown: Any) -> dict[str, Any]:
    raw: Any = getattr(lockdown, "all_values", None)
    if callable(raw):
        raw = raw()
    raw = await _maybe_await(raw)
    return dict(raw) if isinstance(raw, dict) else {}


async def _lockdown_all_values_async(udid: str) -> dict[str, Any]:
    from pymobiledevice3.lockdown import create_using_usbmux

    created: Any = await _maybe_await(create_using_usbmux(serial=udid or None))
    if hasattr(created, "__aenter__"):
        async with created as ld:
            return await _read_all_values(ld)
    return await _read_all_values(created)


def _lockdown_values(udid: str) -> dict[str, Any]:
    def _run_lockdown() -> dict[str, Any]:
        import asyncio

        return asyncio.run(_lockdown_all_values_async(udid)) or {}

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_lockdown).result(timeout=_LOCKDOWN_TIMEOUT_SEC)
    except (FuturesTimeout, OSError, RuntimeError, TypeError, ValueError, ImportError):
        return {}


def _goios_info(udid: str) -> dict[str, Any]:
    output = _run(udid, ["info"], _GOIOS_TIMEOUT_SEC)
    blob = _extract_json_object(_ANSI_RE.sub("", output))
    if not blob:
        return {}
    try:
        raw = json.loads(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _wda_extras(wda: Any) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if wda is None:
        return extra
    status = None
    if hasattr(wda, "status"):
        try:
            status = wda.status() or {}
        except (OSError, RuntimeError, AttributeError, TypeError):
            status = None
    if isinstance(status, dict):
        from autopilot_platform.ap.mobile.ios.device_info import wda_status_to_device_info

        mapped = wda_status_to_device_info(status)
        if mapped.get("ip"):
            extra["ip_address"] = mapped["ip"]
        if mapped.get("wdaVersion"):
            extra["wda_version"] = mapped["wdaVersion"]
        screen = str(mapped.get("screenSize") or "")
        if "x" in screen:
            width, _, height = screen.partition("x")
            extra["resolution_width"] = _int(width)
            extra["resolution_height"] = _int(height)
    if extra.get("resolution_width") and extra.get("resolution_height"):
        return {key: value for key, value in extra.items() if value not in ("", None)}
    if hasattr(wda, "get_window_size"):
        try:
            size = wda.get_window_size() or {}
        except (OSError, RuntimeError, AttributeError, TypeError):
            size = {}
        if isinstance(size, dict):
            width = _int(size.get("width"))
            height = _int(size.get("height"))
            if width and height:
                extra["resolution_width"] = width
                extra["resolution_height"] = height
    return {key: value for key, value in extra.items() if value not in ("", None)}


def collect(udid: str, wda: Any = None) -> dict[str, Any]:
    extra = _wda_extras(wda)
    raw = _lockdown_values(udid)
    if not raw.get("ProductType") and not raw.get("productType"):
        try:
            raw = _goios_info(udid)
        except (OSError, RuntimeError, ValueError, FileNotFoundError):
            raw = raw or {}
    info = parse_lockdown_info(raw, udid)
    info.setdefault("device_id", udid)
    info.setdefault("platform", "ios")
    info.update(extra)
    return info
