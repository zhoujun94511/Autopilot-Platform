"""Platform 进程实例标识：前端用于检测控制面重启并刷新 Runner/设备态。"""

from __future__ import annotations

import uuid

# 每次 Platform 进程启动生成新 ID（lifespan 前已固定）。
PLATFORM_BOOT_ID: str = uuid.uuid4().hex
