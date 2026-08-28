"""与 Platform `/api/v1` 对齐的客户端契约（HTTP JSON），不依赖服务端包。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Optional


API_V1_PREFIX = "/api/v1"
DEFAULT_API_TOKEN = "dev-mc-token"

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


def required_backends(platform: str, backend_mode: str) -> set[str] | None:
    mode = (backend_mode or "auto").strip().lower()
    plat = (platform or "").strip().lower()
    if mode in ("", "auto"):
        return None
    if mode in ("uia2", "android-appium"):
        return {BACKEND_ANDROID_APPIUM}
    if mode in ("wda", "ios-wda"):
        return {BACKEND_IOS_WDA}
    if mode == "ios-appium":
        return {BACKEND_IOS_APPIUM}
    if mode == "appium":
        if plat == "ios":
            return {BACKEND_IOS_APPIUM}
        if plat == "android":
            return {BACKEND_ANDROID_APPIUM}
        return {BACKEND_ANDROID_APPIUM, BACKEND_IOS_APPIUM}
    return {mode}


def backends_ok(
    device_backends: list[str] | tuple[str, ...] | None,
    *,
    platform: str,
    backend_mode: str,
) -> bool:
    backends = {str(x).strip() for x in (device_backends or []) if str(x).strip()}
    required = required_backends(platform, backend_mode)
    plat = (platform or "").strip().lower()
    if required is None:
        if not backends:
            return True
        if plat == "android":
            return BACKEND_ANDROID_APPIUM in backends
        if plat == "ios":
            return bool(backends & {BACKEND_IOS_APPIUM, BACKEND_IOS_WDA})
        return True
    if not backends:
        return True
    return bool(backends & required)


@dataclass
class DeviceInfo:
    udid: str
    platform: str
    name: str = ""
    model: str = ""
    os_version: str = ""
    labels: list[str] = field(default_factory=list)
    state: str = "ready"
    backends: list[str] = field(default_factory=list)
    health_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunnerRegister:
    runner_id: str
    hostname: str = ""
    version: str = "0.1.0"
    capabilities: list[str] = field(default_factory=list)
    host_backends: list[str] = field(default_factory=list)
    registration_source: str = "ide"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HeartbeatIn:
    runner_id: str
    inventory: list[DeviceInfo]
    devices: list[DeviceInfo]
    policy_revision: int = 0
    capabilities: list[str] = field(default_factory=list)
    host_backends: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_id": self.runner_id,
            "devices": [d.to_dict() for d in self.devices],
            "inventory": [d.to_dict() for d in self.inventory],
            "policy_revision": self.policy_revision,
            "capabilities": list(self.capabilities),
            "host_backends": list(self.host_backends),
        }


@dataclass
class ReportIndex:
    report_path: str = ""
    passed: int = 0
    failed: int = 0
    total: int = 0
    duration_ms: int = 0
    summary: str = ""
    job_id: str = ""
    stored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReportIndex | None:
        if not data:
            return None
        return cls(
            report_path=str(data.get("report_path") or ""),
            passed=int(data.get("passed") or 0),
            failed=int(data.get("failed") or 0),
            total=int(data.get("total") or 0),
            duration_ms=int(data.get("duration_ms") or 0),
            summary=str(data.get("summary") or ""),
            job_id=str(data.get("job_id") or ""),
            stored=bool(data.get("stored") or False),
        )


@dataclass
class JobResultIn:
    status: JobStatus
    error: Optional[str] = None
    report: Optional[ReportIndex] = None
    log: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "error": self.error,
            "report": self.report.to_dict() if self.report else None,
            "log": self.log,
        }

    def with_error(self, error: str) -> JobResultIn:
        return replace(self, error=error)


@dataclass
class JobOut:
    id: str
    name: str
    status: JobStatus
    project_dir: str = ""
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    project_id: str = ""
    platform: str = ""
    device_udids: list[str] = field(default_factory=list)
    entry_paths: list[str] = field(default_factory=list)
    parallel: bool = False
    parallel_workers: int = 0
    backend_mode: str = "auto"
    web_engine: str = "selenium"
    wda_bundle: str = ""
    preferred_runner_id: Optional[str] = None
    runner_id: Optional[str] = None
    error: Optional[str] = None
    webhook_url: str = ""
    parent_job_id: Optional[str] = None
    created_by: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobOut:
        st = data.get("status") or JobStatus.PENDING.value
        if isinstance(st, JobStatus):
            status = st
        else:
            status = JobStatus(str(st))
        eng = str(data.get("web_engine") or "selenium").strip().lower()
        if eng not in ("selenium", "playwright"):
            eng = "selenium"
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            status=status,
            project_dir=str(data.get("project_dir") or ""),
            artifact_id=(str(data["artifact_id"]) if data.get("artifact_id") else None),
            app_build_id=(str(data["app_build_id"]) if data.get("app_build_id") else None),
            project_id=str(data.get("project_id") or ""),
            platform=str(data.get("platform") or ""),
            device_udids=[str(x) for x in (data.get("device_udids") or [])],
            entry_paths=[str(x) for x in (data.get("entry_paths") or [])],
            parallel=bool(data.get("parallel") or False),
            parallel_workers=int(data.get("parallel_workers") or 0),
            backend_mode=str(data.get("backend_mode") or "auto"),
            web_engine=eng,
            wda_bundle=str(data.get("wda_bundle") or ""),
            preferred_runner_id=(
                str(data["preferred_runner_id"]) if data.get("preferred_runner_id") else None
            ),
            runner_id=(str(data["runner_id"]) if data.get("runner_id") else None),
            error=(str(data["error"]) if data.get("error") else None),
            webhook_url=str(data.get("webhook_url") or ""),
            parent_job_id=(str(data["parent_job_id"]) if data.get("parent_job_id") else None),
            created_by=str(data.get("created_by") or ""),
        )
