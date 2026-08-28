"""运行配置：IDE / CLI / 无头 API 共用。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..executor import FaultStrategy
from ..keyword_store import KeywordStore
from ...model.mapfile import MapFile
from ...runtime.device_session import DeviceSession


@dataclass
class RunConfig:
    name: str = "Suite"
    mode: str = "sequential"           # sequential | parallel_device
    platform: str = ""                 # parallel 时：android | ios
    parallel_workers: int = 0          # 0 = 使用全部已连接设备
    fault_strategy: FaultStrategy = FaultStrategy.CONTINUE
    base_vars: dict = field(default_factory=dict)
    maps: list[MapFile] = field(default_factory=list)
    keyword_store: Optional[KeywordStore] = None
    device_sessions: list[DeviceSession] = field(default_factory=list)
    cancel_event: Optional[threading.Event] = None
    pause_event: Optional[threading.Event] = None
    on_step: Optional[Callable[[Any], None]] = None
    on_case: Optional[Callable[[Any], None]] = None
    on_context: Optional[Callable[[Any], None]] = None
    parallel_fault_isolation: bool = True   # True=某 worker 失败不杀其他 worker
    fault_times: int = 0                    # 用例失败后再试次数（总尝试 ≤ 1+N）
    parallel_stop_drain_sec: float = 30.0   # 停止后等待各设备交结果的超时秒数
