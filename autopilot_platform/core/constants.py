"""API 前缀、心跳超时、任务状态。"""

from __future__ import annotations

from enum import Enum

from .job_platforms import (
    CAPABILITY_HTTP,
    DEVICELESS_PLATFORMS,
    JOB_PLATFORMS,
    PLATFORM_ANDROID,
    PLATFORM_HTTP,
    PLATFORM_IOS,
    PLATFORM_WEB,
    is_deviceless_platform,
    is_http_platform,
    is_web_platform,
)

API_V1_PREFIX = "/api/v1"

# 开发默认令牌；生产请设环境变量 MC_API_TOKEN
DEFAULT_API_TOKEN = "dev-mc-token"

# Runner 超过该秒数未心跳则视为离线，其设备不进入可用 TR 池
HEARTBEAT_TIMEOUT_SEC = 90

# 设备健康态（Runner 心跳上报；busy 以 DeviceRow.busy_job_id 为准）
DEVICE_STATE_READY = "ready"
DEVICE_STATE_BUSY = "busy"
DEVICE_STATE_ERROR = "error"
DEVICE_STATE_UNAUTHORIZED = "unauthorized"
DEVICE_STATE_OFFLINE = "offline"
# 多 Runner 同时在线挂载同一 UDID 时由 Platform 打标；不可调度
DEVICE_STATE_CONFLICT = "conflict"
DEVICE_STATES_SCHEDULABLE = frozenset({DEVICE_STATE_READY, ""})

# 执行后端标签（设备级 capabilities / 调度过滤）
BACKEND_ANDROID_APPIUM = "android-appium"
BACKEND_IOS_APPIUM = "ios-appium"
BACKEND_IOS_WDA = "ios-wda"


class JobStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


__all__ = [
    "API_V1_PREFIX",
    "DEFAULT_API_TOKEN",
    "HEARTBEAT_TIMEOUT_SEC",
    "DEVICE_STATE_READY",
    "DEVICE_STATE_BUSY",
    "DEVICE_STATE_ERROR",
    "DEVICE_STATE_UNAUTHORIZED",
    "DEVICE_STATE_OFFLINE",
    "DEVICE_STATE_CONFLICT",
    "DEVICE_STATES_SCHEDULABLE",
    "BACKEND_ANDROID_APPIUM",
    "BACKEND_IOS_APPIUM",
    "BACKEND_IOS_WDA",
    "PLATFORM_ANDROID",
    "PLATFORM_IOS",
    "PLATFORM_WEB",
    "PLATFORM_HTTP",
    "JOB_PLATFORMS",
    "DEVICELESS_PLATFORMS",
    "CAPABILITY_HTTP",
    "is_deviceless_platform",
    "is_http_platform",
    "is_web_platform",
    "JobStatus",
]
