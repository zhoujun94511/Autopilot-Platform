"""Android 设备信息快照。

一次 adb shell 拉齐字段；不跑 ``dumpsys wifi`` / ``dumpsys battery``
（三星上可达数秒，且 SSID 不展示）。电量走 sysfs。
只取白名单 getprop，避免全量属性 dump 挤占 USB。
与 scrcpy 画面通道独立：走 per-device ADB worker，不抢 WebRTC 事件循环。
"""

from __future__ import annotations

import re
from typing import Any

_PROBE_BREAK = "###=====AP_INFO_BREAK=====###"
_GETPROP_FIELDS = {
    "ro.product.manufacturer": "manufacturer",
    "ro.product.brand": "_brand_raw",
    "ro.product.model": "model",
    "ro.product.marketname": "market_name",
    "ro.build.version.release": "android_version",
    "ro.build.version.codename": "_codename_raw",
    "ro.build.version.sdk": "_sdk_raw",
    "ro.product.cpu.abi": "abi",
    "ro.serialno": "serial",
    "ro.soc.manufacturer": "soc_manufacturer",
    "ro.soc.model": "_soc_model_primary",
    "ro.boot.hardware.platform": "_soc_model_qualcomm_fallback",
    "ro.boot.hardware": "_soc_model_mtk_fallback",
    "ro.build.id": "build_id",
}
_GETPROP_SCRIPT = ";".join(
    f'echo "[{key}]: [$(getprop {key} 2>/dev/null)]"' for key in _GETPROP_FIELDS
)
_PROBE_SCRIPT = (
    f"{_GETPROP_SCRIPT};"
    f' echo "{_PROBE_BREAK}";'
    " if [ -f /sys/class/power_supply/battery/capacity ]; then"
    "  echo CAP:$(cat /sys/class/power_supply/battery/capacity);"
    "  echo ST:$(cat /sys/class/power_supply/battery/status 2>/dev/null);"
    "  echo TMP:$(cat /sys/class/power_supply/battery/temp 2>/dev/null);"
    " else"
    "  echo CAP:$(head -n1 /sys/class/power_supply/*/capacity 2>/dev/null);"
    "  echo ST:$(head -n1 /sys/class/power_supply/*/status 2>/dev/null);"
    "  echo TMP:$(head -n1 /sys/class/power_supply/*/temp 2>/dev/null);"
    " fi;"
    f' echo "{_PROBE_BREAK}";'
    " df -k /data 2>/dev/null;"
    f' echo "{_PROBE_BREAK}";'
    " cat /proc/meminfo 2>/dev/null;"
    f' echo "{_PROBE_BREAK}";'
    " { ip addr show wlan0 2>/dev/null || ip addr 2>/dev/null; };"
    f' echo "{_PROBE_BREAK}";'
    " wm size 2>/dev/null;"
    f' echo "{_PROBE_BREAK}";'
    " wm density 2>/dev/null;"
    f' echo "{_PROBE_BREAK}";'
    " cat /proc/uptime 2>/dev/null"
)
_PROBE_SECTION_COUNT = 8
_GETPROP_LINE_RE = re.compile(r"^\[([^]]+)]:\s*\[([^]]*)]\s*$")
_DF_RE = re.compile(r"^\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+%", re.MULTILINE)
_RESOLUTION_RE = re.compile(r"Physical size:\s*(\d+)x(\d+)")
_OVERRIDE_RESOLUTION_RE = re.compile(r"Override size:\s*(\d+)x(\d+)")
_DENSITY_RE = re.compile(r"Physical density:\s*(\d+)")
_OVERRIDE_DENSITY_RE = re.compile(r"Override density:\s*(\d+)")
_IPV4_RE = re.compile(r"inet (\d+\.\d+\.\d+\.\d+)")


def _shell(device_id: str, cmd: str, timeout: float = 10.0) -> str:
    try:
        # noinspection PyPackageRequirements
        from adbutils import adb  # type: ignore[import-untyped]

        return adb.device(device_id).shell(cmd, timeout=timeout) or ""
    except (RuntimeError, OSError, TimeoutError, ImportError):
        return ""


def _try_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def parse_all_props(raw: str) -> dict[str, str]:
    wanted = set(_GETPROP_FIELDS)
    out: dict[str, str] = {}
    for line in raw.splitlines():
        match = _GETPROP_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in wanted:
            out[key] = match.group(2).strip()
    return out


def parse_battery(dump: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in dump.splitlines():
        line = line.strip()
        if line.startswith("level:") or line.startswith("CAP:"):
            out["battery_level"] = _try_int(line.split(":", 1)[1])
        elif line.startswith("status:") or line.startswith("ST:"):
            raw = line.split(":", 1)[1].strip()
            code = _try_int(raw)
            if code is not None:
                out["battery_status"] = {
                    1: "Unknown",
                    2: "Charging",
                    3: "Discharging",
                    4: "Not charging",
                    5: "Full",
                }.get(code, str(code))
            elif raw:
                out["battery_status"] = raw
        elif line.startswith("temperature:") or line.startswith("TMP:"):
            temp = _try_int(line.split(":", 1)[1])
            if temp is not None:
                out["battery_temp_c"] = temp / 10.0
    return out


def parse_df(df_output: str) -> dict[str, Any]:
    match = _DF_RE.search(df_output)
    if not match:
        return {}
    total_kb, used_kb, _avail_kb = (int(group) for group in match.groups())
    return {
        "storage_used_bytes": used_kb * 1024,
        "storage_total_bytes": total_kb * 1024,
    }


def parse_meminfo(mem: str) -> dict[str, Any]:
    total_kb = avail_kb = None
    for line in mem.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = _try_int(line.split(":", 1)[1].strip().split()[0])
        elif line.startswith("MemAvailable:"):
            avail_kb = _try_int(line.split(":", 1)[1].strip().split()[0])
    if total_kb is None:
        return {}
    out = {"memory_total_bytes": total_kb * 1024}
    if avail_kb is not None:
        out["memory_used_bytes"] = (total_kb - avail_kb) * 1024
    return out


def parse_resolution(wm_size: str) -> dict[str, Any]:
    match = _OVERRIDE_RESOLUTION_RE.search(wm_size) or _RESOLUTION_RE.search(wm_size)
    if not match:
        return {}
    return {
        "resolution_width": int(match.group(1)),
        "resolution_height": int(match.group(2)),
    }


def parse_density(wm_density: str) -> int | None:
    match = _OVERRIDE_DENSITY_RE.search(wm_density) or _DENSITY_RE.search(wm_density)
    return int(match.group(1)) if match else None


def parse_ip(ip_output: str) -> str | None:
    for line in ip_output.splitlines():
        match = _IPV4_RE.search(line)
        if match:
            ip = match.group(1)
            if not ip.startswith("127."):
                return ip
    return None


def parse_uptime(uptime_proc: str) -> int | None:
    parts = uptime_proc.strip().split()
    if not parts:
        return None
    try:
        return int(float(parts[0]))
    except (ValueError, TypeError):
        return None


def _apply_props(info: dict[str, Any], props: dict[str, str]) -> None:
    manufacturer = props.get("ro.product.manufacturer", "")
    if manufacturer:
        info["manufacturer"] = manufacturer
    brand = props.get("ro.product.brand", "")
    if brand and brand.lower() != manufacturer.lower():
        info["brand"] = brand
    market = props.get("ro.product.marketname", "")
    if market:
        info["market_name"] = market
    model = props.get("ro.product.model", "")
    if model:
        info["model"] = model
    release = props.get("ro.build.version.release", "")
    if release:
        info["android_version"] = release
    codename = props.get("ro.build.version.codename", "")
    if codename and codename != "REL":
        info["android_codename"] = codename
    sdk = _try_int(props.get("ro.build.version.sdk", ""))
    if sdk is not None:
        info["sdk"] = sdk
    abi = props.get("ro.product.cpu.abi", "")
    if abi:
        info["abi"] = abi
    serial = props.get("ro.serialno", "")
    if serial:
        info["serial"] = serial
    soc_mfr = props.get("ro.soc.manufacturer", "")
    if soc_mfr:
        info["soc_manufacturer"] = soc_mfr
    soc_model = (
        props.get("ro.soc.model", "")
        or props.get("ro.boot.hardware.platform", "")
        or props.get("ro.boot.hardware", "")
    )
    if soc_model:
        info["soc_model"] = soc_model
    build_id = props.get("ro.build.id", "")
    if build_id:
        info["build_id"] = build_id


def parse_probe_output(raw: str, device_id: str) -> dict[str, Any]:
    info: dict[str, Any] = {"device_id": device_id, "platform": "android"}
    sections = raw.split(_PROBE_BREAK)
    while len(sections) < _PROBE_SECTION_COUNT:
        sections.append("")
    (
        props_raw,
        battery_raw,
        df_raw,
        mem_raw,
        ip_raw,
        wm_size_raw,
        wm_density_raw,
        uptime_raw,
    ) = sections[:_PROBE_SECTION_COUNT]
    _apply_props(info, parse_all_props(props_raw))
    info.update(parse_battery(battery_raw))
    info.update(parse_df(df_raw))
    info.update(parse_meminfo(mem_raw))
    ip = parse_ip(ip_raw)
    if ip:
        info["ip_address"] = ip
    info.update(parse_resolution(wm_size_raw))
    density = parse_density(wm_density_raw)
    if density is not None:
        info["density_dpi"] = density
    uptime = parse_uptime(uptime_raw)
    if uptime is not None:
        info["uptime_seconds"] = uptime
    info["connection_type"] = "wifi" if ":" in device_id else "usb"
    return info


def collect(device_id: str) -> dict[str, Any]:
    raw = _shell(device_id, _PROBE_SCRIPT, timeout=10.0)
    return parse_probe_output(raw, device_id)
