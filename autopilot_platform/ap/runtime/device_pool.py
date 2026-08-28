"""设备池：从已连接 UDID 列表构建 DeviceSession；保留 shard_cases 供其它分发策略使用。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .device_session import DeviceSession
from .device_runtime import DeviceRuntimeLease

if TYPE_CHECKING:
    from ..model.testcase import TestCase


def normalize_platform(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p.startswith("ios"):
        return "ios"
    if p.startswith("android"):
        return "android"
    raise ValueError(f"不支持的平台：{platform!r}")


def build_sessions(platform: str, udids: list[str], *,
                   workers: int = 0, wda_bundle: str = "",
                   backend_mode: str = "auto",
                   lease: DeviceRuntimeLease | None = None) -> list[DeviceSession]:
    """为并行 worker 构建 DeviceSession 列表。workers=0 表示用全部已连接设备。"""
    plat = normalize_platform(platform)
    devices = [u for u in udids if str(u).strip()]
    if not devices:
        raise RuntimeError(f"没有可用的 {plat} 设备 UDID")
    n = workers if workers > 0 else len(devices)
    n = min(n, len(devices))
    out: list[DeviceSession] = []
    for i in range(n):
        sess = DeviceSession.for_device(
            plat, devices[i], wda_bundle=wda_bundle, backend_mode=backend_mode)
        if lease is not None:
            lease.hold([sess.udid])
        out.append(sess)
    return out


def shard_cases(cases: list[TestCase], n: int) -> list[list]:
    """Round-robin 分片：case[i] -> shard[i % n]。

    当前 IDE「批量并行」默认是每台完整复跑全部用例，不走此函数；
    保留供 CLI/其它分发策略复用。
    """
    if n <= 0:
        raise ValueError("shard count must be positive")
    shards: list[list] = [[] for _ in range(n)]
    for i, tc in enumerate(cases):
        shards[i % n].append(tc)
    return shards
