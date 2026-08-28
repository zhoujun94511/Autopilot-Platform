"""本机设备枚举（TR 上报用）。"""

from __future__ import annotations

from autopilot_platform.core.schemas import DeviceInfo


def list_android_udids() -> list[str]:
    from .local_devices import list_android_udids as _list

    return _list()


def list_ios_udids() -> list[str]:
    from .local_devices import list_ios_udids as _list

    return _list()


def list_local_devices() -> list[DeviceInfo]:
    from .local_devices import list_local_devices as _list

    return [
        DeviceInfo(
            udid=d.udid,
            platform=d.platform,
            name=d.name or "",
            model=d.model or "",
            os_version=d.os_version or "",
            state=d.state or "ready",
            backends=list(d.backends or ()),
            health_note=d.health_note or "",
            labels=list(d.labels or ()),
        )
        for d in _list()
    ]


def probe_host_capabilities() -> tuple[list[str], list[str]]:
    from .local_devices import probe_host_capabilities as _probe

    return _probe()


def format_probe_report() -> str:
    from .local_devices import format_probe_report as _fmt

    return _fmt()
