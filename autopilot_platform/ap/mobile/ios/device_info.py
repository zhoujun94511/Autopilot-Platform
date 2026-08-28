"""iOS 设备信息：WDA /status 与 Appium caps 统一查询（供 mobile_get_deviceinfo）。"""

from __future__ import annotations

from typing import Any

from .runtime import is_ios_driver

# deviceInfo 参数别名 → 归一化后的键
_DEVICE_INFO_ALIASES: dict[str, str] = {
    "androidversion": "version",
    "platformversion": "version",
    "iosversion": "version",
    "release": "version",
    "sdkversion": "sdk",
    "sdkint": "sdk",
    "model": "model",
    "device": "model",
    "ip": "ip",
    "wdaversion": "wdaVersion",
    "os": "os",
    "platformname": "platformName",
    "screensize": "screenSize",
    "resolution": "screenSize",
    "size": "screenSize",
}

def wda_status_to_device_info(status: dict) -> dict:
    """WDA GET /status → 与 mobile_get_deviceinfo 一致的键表。"""
    s = status or {}
    osd = s.get("os") or {}
    ver = str(osd.get("version", "") or "")
    sdk = str(osd.get("sdkVersion", "") or "")
    dev = str(s.get("device", "") or "")
    ios_block = s.get("ios") or {}
    w, h = 0, 0
    # noinspection PyBroadException
    try:
        sz = (s.get("session") or {}).get("window") or {}
        w = int(sz.get("width", 0) or 0)
        h = int(sz.get("height", 0) or 0)
    except Exception:
        pass
    screen = f"{w}x{h}" if w and h else ""
    return {
        "version": ver,
        "platformVersion": ver,
        "iosVersion": ver,
        "release": ver,
        "os": str(osd.get("name", "") or ""),
        "platformName": str(osd.get("name", "") or "iOS"),
        "sdk": sdk,
        "sdkVersion": sdk,
        "model": dev,
        "device": dev,
        "ip": str(ios_block.get("ip", "") or ""),
        "wdaVersion": str((s.get("build") or {}).get("version", "") or ""),
        "screenSize": screen,
        "resolution": screen,
        "size": screen,
    }


_IOS_KNOWN_KEYS = frozenset({
    "version", "platformVersion", "iosVersion", "release",
    "sdk", "sdkVersion", "model", "device", "ip", "wdaVersion",
    "os", "platformName", "screenSize",
})


def _wda_base_url_from_caps(caps: dict) -> str:
    for k in ("webDriverAgentUrl", "appium:webDriverAgentUrl"):
        v = caps.get(k)
        if v:
            return str(v).rstrip("/")
    port = caps.get("wdaLocalPort") or caps.get("appium:wdaLocalPort") or 8100
    return f"http://127.0.0.1:{port}"


def fetch_wda_status(driver: Any) -> dict | None:
    """Appium XCUITest 等无 device_info 时，经 caps 中的 WDA URL 拉 /status。"""
    client = getattr(driver, "wda_client", None) or getattr(driver, "_c", None)
    if client is not None and hasattr(client, "status"):
        return client.status() or {}
    caps = getattr(driver, "capabilities", None) or {}
    base = _wda_base_url_from_caps(caps)
    # noinspection PyBroadException
    try:
        import httpx
        r = httpx.get(f"{base}/status", timeout=5)
        if r.status_code != 200:
            return None
        body = r.json()
        return body.get("value") if isinstance(body.get("value"), dict) else body
    except Exception:
        return None


def driver_device_info(driver: Any) -> dict[str, str]:
    """统一 iOS 设备信息表（WDA-direct / Appium + webDriverAgentUrl）。"""
    info: dict[str, str] = {}
    if hasattr(driver, "device_info"):
        info = dict(driver.device_info() or {})
    if not info:
        status = fetch_wda_status(driver)
        if status:
            info = wda_status_to_device_info(status)
    caps = getattr(driver, "capabilities", None) or {}
    if not str(info.get("version") or "").strip():
        ver = caps.get("platformVersion") or caps.get("appium:platformVersion")
        if ver:
            info["version"] = str(ver)
            info["platformVersion"] = str(ver)
    if not str(info.get("model") or "").strip():
        model = caps.get("deviceName") or caps.get("appium:deviceName")
        if model:
            info["model"] = str(model)
            info["device"] = str(model)
    if not str(info.get("ip") or "").strip():
        ip = caps.get("deviceIp") or caps.get("ip")
        if ip:
            info["ip"] = str(ip)
    return info


def _normalize_key(device_info: str) -> str:
    raw = (device_info or "").strip()
    if not raw:
        return "version"
    low = raw.lower()
    return _DEVICE_INFO_ALIASES.get(low, raw)


def lookup_ios_device_info(driver: Any, device_info: str) -> str:
    """读取 iOS 设备信息项；无值时抛 NotImplementedKeyword。"""
    from ...keywords.registry import NotImplementedKeyword

    key = _normalize_key(device_info)
    info = driver_device_info(driver)
    caps = getattr(driver, "capabilities", None) or {}
    if not info and is_ios_driver(driver):
        ver = caps.get("platformVersion") or caps.get("version")
        if ver:
            info = {"version": str(ver), "platformVersion": str(ver)}
    # 直接键
    for candidate in (key, device_info, _normalize_key(device_info)):
        if candidate in info and str(info[candidate]).strip():
            return str(info[candidate])
    # caps 回退
    if key in ("version", "platformVersion") and caps.get("platformVersion"):
        return str(caps["platformVersion"])
    if key == "model" and caps.get("deviceName"):
        return str(caps["deviceName"])
    if key == "udid" and caps.get("udid"):
        return str(caps["udid"])
    known = ", ".join(sorted(_IOS_KNOWN_KEYS))
    raise NotImplementedKeyword(
        f"iOS 设备信息项[{device_info}]不支持或为空；可用项：{known}"
    )
