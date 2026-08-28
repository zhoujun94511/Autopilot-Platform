"""进程内设备运行时：UDID 粘滞绑定独立端口族。

一台设备在本进程生命周期内固定占用同一套 Appium/UIA2/WDA 端口，
避免并行时按勾选顺序重排 slot 导致残留 WDA/UIA2 串台。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from .port_allocator import PortAllocator, PortSet


def _max_slots() -> int:
    try:
        return max(2, min(64, int(os.getenv("AUTOPILOT_MAX_DEVICE_SLOTS", "32"))))
    except (TypeError, ValueError):
        return 32


@dataclass(frozen=True)
class IsolatedRuntime:
    udid: str
    platform: str
    ports: PortSet

    @property
    def slot(self) -> int:
        return self.ports.slot

    @property
    def appium_url(self) -> str:
        return f"http://127.0.0.1:{self.ports.appium_port}"

    @property
    def uses_local_appium(self) -> bool:
        plat = (self.platform or "").strip().lower()
        return plat.startswith("android") or plat.startswith("ios")


class DeviceRuntimeRegistry:
    """UDID → 端口粘滞表 + 引用计数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_udid: dict[str, IsolatedRuntime] = {}
        self._refs: dict[str, int] = {}
        self._slot_owner: dict[int, str] = {}

    def acquire(self, udid: str, platform: str) -> IsolatedRuntime:
        uid = (udid or "").strip()
        if not uid:
            raise RuntimeError("acquire_device_runtime 需要非空 UDID")
        plat = (platform or "").strip().lower() or "android"
        recycle_port: int | None = None
        with self._lock:
            existing = self._by_udid.get(uid)
            if existing is not None:
                self._refs[uid] = int(self._refs.get(uid) or 0) + 1
                if existing.platform != plat and plat in {"android", "ios"}:
                    return IsolatedRuntime(udid=uid, platform=plat, ports=existing.ports)
                return existing
            slot, recycle_port = self._alloc_slot_unlocked(uid)
            ports = PortAllocator.ports_for_slot(slot)
            rt = IsolatedRuntime(udid=uid, platform=plat, ports=ports)
            self._by_udid[uid] = rt
            self._slot_owner[slot] = uid
            self._refs[uid] = 1
        if recycle_port is not None:
            _stop_recycled_appium(recycle_port)
        return rt

    def release(self, udid: str) -> None:
        uid = (udid or "").strip()
        if not uid:
            return
        with self._lock:
            n = int(self._refs.get(uid) or 0) - 1
            if n > 0:
                self._refs[uid] = n
                return
            self._refs.pop(uid, None)
            # 粘滞：引用归零仍保留端口映射，供下一 Job 热复用。
            # 仅当槽位耗尽时，acquire 会回收 ref=0 的最旧条目。

    def peek(self, udid: str) -> IsolatedRuntime | None:
        uid = (udid or "").strip()
        if not uid:
            return None
        with self._lock:
            return self._by_udid.get(uid)

    def reset(self) -> None:
        with self._lock:
            self._by_udid.clear()
            self._refs.clear()
            self._slot_owner.clear()

    def _alloc_slot_unlocked(self, uid: str) -> tuple[int, int | None]:
        max_slots = _max_slots()
        for slot in range(max_slots):
            if slot not in self._slot_owner:
                return slot, None
        # release() 在 ref=0 时会 pop _refs，粘滞项只留在 _by_udid / _slot_owner。
        idle = [
            u for u in self._by_udid
            if int(self._refs.get(u) or 0) <= 0
        ]
        for victim in idle:
            rt = self._by_udid.pop(victim, None)
            self._refs.pop(victim, None)
            if rt is not None:
                self._slot_owner.pop(rt.slot, None)
                return rt.slot, rt.ports.appium_port
        raise RuntimeError(
            f"设备隔离槽位已满（max={max_slots}），无法为 UDID={uid} 分配端口"
        )


_REGISTRY = DeviceRuntimeRegistry()


def _stop_recycled_appium(port: int) -> None:
    """槽位被新 UDID 回收后，停掉旧端口上由我们拉起的 Appium，避免串台。"""
    try:
        from ..keywords.mobile.appium_server import stop_local_appium

        stop_local_appium("127.0.0.1", int(port))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        pass


def acquire_device_runtime(udid: str, platform: str) -> IsolatedRuntime:
    return _REGISTRY.acquire(udid, platform)


def release_device_runtime(udid: str) -> None:
    _REGISTRY.release(udid)


class DeviceRuntimeLease:
    """本趟 acquire 的 UDID 引用，离开 with 时一律 release。"""

    def __init__(self) -> None:
        self._udids: list[str] = []

    def hold(self, udids: list[str]) -> None:
        seen = set(self._udids)
        for raw in udids:
            uid = str(raw).strip()
            if uid and uid not in seen:
                seen.add(uid)
                self._udids.append(uid)

    def __enter__(self) -> DeviceRuntimeLease:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for uid in self._udids:
            release_device_runtime(uid)
        self._udids = []


def peek_device_runtime(udid: str) -> IsolatedRuntime | None:
    return _REGISTRY.peek(udid)


def reset_device_runtimes_for_tests() -> None:
    _REGISTRY.reset()


def runtimes_for_vars(base_vars: dict | None) -> list[IsolatedRuntime]:
    """从 suite base_vars 解析本趟涉及的设备运行时。

    单设备上下文（含并行 worker）优先 ``__device_udid__``，避免把兄弟设备的
    Appium 一并停掉。仅当没有单机 UDID 时才展开 ``__parallel_device_udids__``。
    """
    bv = base_vars or {}
    one = str(bv.get("__device_udid__") or "").strip()
    udids: list[str] = [one] if one else []
    if not udids:
        raw = bv.get("__parallel_device_udids__")
        if isinstance(raw, (list, tuple)):
            udids = [str(u).strip() for u in raw if str(u).strip()]
    out: list[IsolatedRuntime] = []
    for uid in udids:
        rt = peek_device_runtime(uid)
        if rt is not None:
            out.append(rt)
    return out
