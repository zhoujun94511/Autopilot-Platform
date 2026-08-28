"""本机设备隔离端口族：Appium / UIA2 / WDA / go-ios 隧道 / MJPEG。

slot=0 与历史单设备默认一致（Appium 4723、UIA2 systemPort 8200、WDA 8100）。
多设备必须使用不同 slot，禁止共用 4723。
"""

from __future__ import annotations

import os
import socket
from contextlib import closing
from dataclasses import dataclass

from ..mobile.ios_bootstrap import (
    DEFAULT_MJPEG_PORT,
    DEFAULT_TUNNEL_INFO_PORT,
    DEFAULT_WDA_PORT,
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


WDA_BASE = _env_int("AUTOPILOT_WDA_BASE_PORT", DEFAULT_WDA_PORT)
TUNNEL_BASE = _env_int("AUTOPILOT_TUNNEL_BASE_PORT", DEFAULT_TUNNEL_INFO_PORT)
MJPEG_BASE = _env_int("AUTOPILOT_MJPEG_BASE_PORT", DEFAULT_MJPEG_PORT)
TUNNEL_SLOT_STEP = _env_int("AUTOPILOT_TUNNEL_SLOT_STEP", 10)
APPIUM_BASE = _env_int("AUTOPILOT_APPIUM_BASE_PORT", 4723)
UIA2_SYSTEM_BASE = _env_int("AUTOPILOT_UIA2_SYSTEM_PORT_BASE", 8200)
CHROMEDRIVER_BASE = _env_int("AUTOPILOT_CHROMEDRIVER_PORT_BASE", 9515)
UIA2_MJPEG_BASE = _env_int("AUTOPILOT_UIA2_MJPEG_PORT_BASE", 7810)


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


@dataclass(frozen=True)
class PortSet:
    slot: int
    wda_port: int
    tunnel_port: int
    mjpeg_port: int
    appium_port: int
    system_port: int
    chromedriver_port: int
    uia2_mjpeg_port: int

    def isolation_ports(self) -> tuple[int, ...]:
        return (
            self.appium_port,
            self.system_port,
            self.chromedriver_port,
            self.uia2_mjpeg_port,
            self.wda_port,
            self.tunnel_port,
            self.mjpeg_port,
        )


class PortAllocator:
    """按 slot 计算端口族；slot=0 与单设备默认行为一致。"""

    @staticmethod
    def ports_for_slot(slot: int) -> PortSet:
        n = int(slot)
        return PortSet(
            slot=n,
            wda_port=WDA_BASE + n,
            tunnel_port=TUNNEL_BASE + n * TUNNEL_SLOT_STEP,
            mjpeg_port=MJPEG_BASE + n,
            appium_port=APPIUM_BASE + n,
            system_port=UIA2_SYSTEM_BASE + n,
            chromedriver_port=CHROMEDRIVER_BASE + n,
            uia2_mjpeg_port=UIA2_MJPEG_BASE + n,
        )

    def acquire(self, slot: int, *, check_free: bool = False) -> PortSet:
        ps = self.ports_for_slot(slot)
        if check_free:
            busy = [p for p in ps.isolation_ports() if not is_port_free(p)]
            if busy:
                raise RuntimeError(f"并行 slot {slot} 端口被占用：{busy}")
        return ps


def assign_ports_for_udid(
    udid: str,
    *,
    devices: list[str] | None = None,
    max_slots: int = 16,
) -> PortSet:
    """为 UDID 扫描空闲 slot（不写入进程级粘滞表）。

    机房/批跑请用 ``device_runtime.acquire_device_runtime``，按 UDID 粘滞。
    """
    udid = (udid or "").strip()
    devs = sorted({d.strip() for d in (devices or []) if str(d or "").strip()})
    preferred = devs.index(udid) if udid and udid in devs else 0
    allocator = PortAllocator()
    upper = min(max_slots, max(preferred + len(devs) + 4, 8))
    last_err = ""
    for slot in range(preferred, upper):
        try:
            return allocator.acquire(slot, check_free=True)
        except RuntimeError as exc:
            last_err = str(exc)
            continue
    raise RuntimeError(
        f"无可用隔离端口（UDID={udid or '?'}，"
        f"首选 slot={preferred}，{last_err}）"
    )


def port_set_to_ctx_vars(ps: PortSet) -> dict[str, int | str]:
    """写入 ExecutionContext 的隔离端口变量。"""
    return {
        "__wda_local_port__": ps.wda_port,
        "__tunnel_info_port__": ps.tunnel_port,
        "__mjpeg_local_port__": ps.mjpeg_port,
        "__worker_slot__": ps.slot,
        "__appium_server__": f"http://127.0.0.1:{ps.appium_port}",
        "__uia2_system_port__": ps.system_port,
        "__chromedriver_port__": ps.chromedriver_port,
        "__uia2_mjpeg_port__": ps.uia2_mjpeg_port,
    }
