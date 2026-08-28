"""运行时支撑层（不依赖 GUI）：日志、并行设备会话、端口分配等。"""

from .device_session import DeviceSession
from .device_pool import build_sessions, shard_cases, normalize_platform
from .port_allocator import PortAllocator, assign_ports_for_udid, port_set_to_ctx_vars

__all__ = [
    "DeviceSession",
    "build_sessions",
    "shard_cases",
    "normalize_platform",
    "PortAllocator",
    "assign_ports_for_udid",
    "port_set_to_ctx_vars",
]
