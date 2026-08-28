"""Pydantic 请求/响应模型（Runner ↔ Platform / 管理台用户）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, get_args

from pydantic import BaseModel, Field, model_validator

from .constants import JOB_PLATFORMS, JobStatus
from .job_platforms import (
    BACKEND_MODE_MAX_LEN,
    apply_deviceless_run_target as apply_deviceless_run_target,
    normalize_stored_backend_mode,
)
from .webhook_security import validate_webhook_url


def normalize_web_engine(engine: str | None, platform: str | None = None) -> str:
    """规范化 web_engine；非 web 平台恒为 selenium。"""
    p = (platform or "").strip().lower()
    if p and p != "web":
        return "selenium"
    eng = (engine or "selenium").strip().lower()
    if eng not in ("selenium", "playwright"):
        raise ValueError("web_engine must be selenium or playwright")
    return eng


class DeviceInfo(BaseModel):
    """Runner 上报的本机设备（仅进入 TR 池，与 IDE 本地池无关）。"""

    udid: str
    platform: str = Field(..., description="android | ios | web | ...")
    name: str = ""
    model: str = ""
    os_version: str = ""
    labels: list[str] = Field(default_factory=list)
    state: str = Field(
        default="ready",
        description="ready | busy | error | unauthorized | offline | conflict",
    )
    backends: list[str] = Field(
        default_factory=list,
        description="如 android-appium, ios-appium, ios-wda",
    )
    health_note: str = ""


class RunnerRegister(BaseModel):
    runner_id: str = Field(..., min_length=1, description="稳定唯一 id，如主机名+UUID")
    hostname: str = ""
    version: str = "0.1.0"
    capabilities: list[str] = Field(
        default_factory=list,
        description="如 android, ios, parallel, report",
    )
    host_backends: list[str] = Field(
        default_factory=list,
        description="本机可提供的执行后端，如 android-appium / ios-wda",
    )
    registration_source: str = Field(
        default="platform",
        description="ide | platform | managed；owner 由服务端鉴权上下文确定",
    )


class RunnerOut(BaseModel):
    runner_id: str
    hostname: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    last_heartbeat_at: Optional[datetime] = None
    online: bool = False
    has_token: bool = False
    org_id: str = ""
    project_ids: list[str] = Field(default_factory=list)
    owner_user_id: str = ""
    registration_source: str = "platform"
    device_selection_mode: str = "all"
    selected_device_udids: list[str] = Field(default_factory=list)
    device_policy_revision: int = 0


class RunnerTokenIssue(BaseModel):
    """签发/轮换 Runner Token 时可同时绑定作用域。

    ``org_id`` / ``project_ids`` 为 ``None`` 时保留节点已有作用域；
    显式传空字符串 / 空列表则清除对应限制。
    """

    org_id: Optional[str] = None
    project_ids: Optional[list[str]] = None


class RunnerScopePatch(BaseModel):
    """更新 Runner Token / 节点作用域；省略字段表示不改。"""

    org_id: Optional[str] = None
    project_ids: Optional[list[str]] = None


class RunnerTokenOut(BaseModel):
    runner_id: str
    api_token: str
    note: str = "仅显示一次，请妥善保存"
    org_id: str = ""
    project_ids: list[str] = Field(default_factory=list)


class RunnerDeviceInventoryItem(DeviceInfo):
    registered: bool = False
    busy: bool = False
    reserved: bool = False
    occupancy_kind: str = ""
    occupancy_username: str = ""
    occupancy_start_at: Optional[datetime] = None
    occupancy_end_at: Optional[datetime] = None
    occupancy_reference: str = ""
    occupancy_reason: str = ""
    rejection_reason: str = ""


class RunnerDeviceInventoryOut(BaseModel):
    runner_id: str
    org_id: str = ""
    selection_mode: str = "all"
    selected_udids: list[str] = Field(default_factory=list)
    policy_revision: int = 0
    devices: list[RunnerDeviceInventoryItem] = Field(default_factory=list)


class RunnerDeviceSelectionIn(BaseModel):
    action: str = Field(
        default="set", description="set | register | unregister"
    )
    udids: list[str] = Field(default_factory=list)


class RunnerDeviceSelectionOut(BaseModel):
    runner_id: str
    selection_mode: str = "include"
    selected_udids: list[str] = Field(default_factory=list)
    policy_revision: int = 0
    registered: list[str] = Field(default_factory=list)
    unregistered: list[str] = Field(default_factory=list)
    rejected: dict[str, str] = Field(default_factory=dict)


class RunnerProvisionIn(BaseModel):
    runner_id: str = Field(..., min_length=1, max_length=128)
    org_id: str = ""
    project_ids: list[str] = Field(default_factory=list)


class RunnerProvisionOut(RunnerTokenOut):
    command: str


class ManagedRunnerStartIn(BaseModel):
    """启动本机托管 Runner（可选绑定 org / project 作用域）。"""

    org_id: Optional[str] = None
    project_ids: Optional[list[str]] = None
    poll_interval: float = 3.0


class ManagedRunnerStatusOut(BaseModel):
    """本机托管 Runner 状态（仅 Platform 同机 subprocess）。"""

    enabled: bool
    running: bool
    managed: bool = False
    pid: Optional[int] = None
    runner_id: str = "managed-local"
    started_at: Optional[datetime] = None
    last_error: str = ""
    exit_code: Optional[int] = None
    log_tail: list[str] = Field(default_factory=list)
    log_file: str = ""
    cli_command: str = ""
    note: str = (
        "浏览器不能在用户 PC 上直接起进程；"
        "本接口仅在 Platform 与 Runner 同机时由服务端子进程托管。"
        "远程节点请用 CLI/服务启动，Web 仅支持注销。"
    )


class ManagedRunnerLogsOut(BaseModel):
    runner_id: str
    lines: list[str] = Field(default_factory=list)
    running: bool = False
    pid: Optional[int] = None
    log_file: str = ""


class DeviceMaintenanceIn(BaseModel):
    disabled: bool
    # 停用时是否同时中断在跑任务并腾空设备（“停用即腾空”）；仅在 disabled=True 时生效
    release: bool = False


class DeviceReservationCreate(BaseModel):
    duration_minutes: int = Field(default=60, ge=1, le=24 * 60)
    reason: str = Field(default="", max_length=512)


class DeviceReservationOut(BaseModel):
    id: str
    device_id: str
    user_id: str
    username: str = ""
    reason: str = ""
    status: str = "active"
    start_at: datetime
    expires_at: datetime
    released_at: Optional[datetime] = None
    can_release: bool = False


class DeviceRemoteSessionCreate(BaseModel):
    """创建远控会话；可选覆盖默认时长（分钟）。"""

    duration_minutes: int = Field(default=60, ge=1, le=24 * 60)
    max_viewers: int = Field(default=5, ge=0, le=32)


class IceServerOut(BaseModel):
    urls: list[str] = Field(default_factory=list)
    username: str = ""
    credential: str = ""


class DeviceRemoteTransportOut(BaseModel):
    signaling: str = "http"
    media: str = "http"
    command: str = "http"
    websocket_path: str = ""


class DeviceRemoteSessionOut(BaseModel):
    id: str
    device_id: str
    runner_id: str
    udid: str = ""
    platform: str = ""
    reservation_id: str = ""
    user_id: str = ""
    username: str = ""
    status: str = "pending"
    capabilities: list[str] = Field(default_factory=list)
    error_message: str = ""
    created_at: datetime
    expires_at: datetime
    closed_at: Optional[datetime] = None
    access_token: str = ""
    signaling_base_path: str = ""
    participant_id: str = ""
    participant_role: str = "controller"
    viewer_count: int = 0
    max_viewers: int = 5
    ice_servers: list[IceServerOut] = Field(default_factory=list)
    transport: DeviceRemoteTransportOut = Field(
        default_factory=DeviceRemoteTransportOut
    )


class DeviceRemoteCommandOut(BaseModel):
    """Runner 拉取的 pending/ready 远控指令。"""

    session_id: str
    device_id: str
    udid: str
    platform: str
    status: str
    capabilities: list[str] = Field(default_factory=list)
    expires_at: datetime
    access_token: str = ""
    ice_servers: list[IceServerOut] = Field(default_factory=list)


class DeviceRemotePrewarmHintOut(BaseModel):
    """Runner 占用后 soft prewarm：已 reservation、尚无 active 远控会话的设备。"""

    device_id: str
    udid: str
    platform: str


class DeviceRemoteParticipantJoinIn(BaseModel):
    role: str = Field(default="viewer", pattern="^(controller|viewer)$")
    connection_id: str = Field(default="", max_length=128)


class DeviceRemoteParticipantOut(BaseModel):
    id: str
    session_id: str
    user_id: str = ""
    username: str = ""
    role: str = "viewer"
    connection_id: str = ""
    status: str = "joining"
    joined_at: datetime
    last_seen_at: datetime
    left_at: Optional[datetime] = None


class DeviceRemoteEnvelope(BaseModel):
    channel: str = Field(
        ..., description="signaling | media | command | event"
    )
    type: str = Field(
        ..., description="request | result | progress | error | event | ping | pong"
    )
    name: str = ""
    request_id: str = ""
    participant_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    progress: Optional[float] = Field(default=None, ge=0, le=1)
    error_code: str = ""
    error_message: str = ""


class DeviceRemoteCommandIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    request_id: str = Field(default="", max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


class DeviceRemoteCommandStatusOut(BaseModel):
    request_id: str
    name: str = ""
    status: str = "accepted"
    progress: float = 0
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""


class DeviceRemoteStreamConfig(BaseModel):
    bitrate: Optional[int] = Field(default=None, ge=500_000, le=20_000_000)
    max_fps: Optional[int] = Field(default=None, ge=1, le=60)
    max_width: Optional[int] = Field(default=None, ge=0, le=1920)
    i_frame_interval: Optional[int] = Field(default=None, ge=1, le=8)
    adaptive: Optional[bool] = None
    jpeg_quality: Optional[int] = Field(default=None, ge=10, le=90)


class DeviceRemoteRunnerStatusIn(BaseModel):
    status: str = Field(..., description="ready | connected | failed | closed")
    error_message: str = Field(default="", max_length=512)
    capabilities: list[str] = Field(default_factory=list)


class SignalingMessageIn(BaseModel):
    """WebRTC 信令载荷（SDP 或 ICE candidate JSON）。"""

    type: str = Field(..., description="offer | answer | ice")
    sdp: str = ""
    candidate: dict[str, Any] = Field(default_factory=dict)
    # browser | runner — 决定对端从哪侧 poll
    from_role: str = Field(default="browser", description="browser | runner")
    participant_id: str = Field(default="", max_length=128)
    participant_role: str = Field(
        default="",
        max_length=32,
        description="controller | viewer；browser 侧由服务端按参与者身份覆盖",
    )


class SignalingPollOut(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    session_status: str = ""


class MediaMessageIn(BaseModel):
    """远控媒体/命令旁路（与 SDP 队列隔离）。"""

    type: str = Field(..., description="frame | input | command | command_reply")
    from_role: str = Field(default="browser", description="browser | runner")
    mime: str = Field(default="image/jpeg", max_length=64)
    data_b64: str = Field(default="", description="JPEG base64（type=frame）")
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    ts: float = Field(default=0)
    payload: Any = Field(default_factory=dict, description="触控/按键（type=input）")


class MediaPollOut(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    session_status: str = ""


class DeviceLogLinesIn(BaseModel):
    """Runner 向 Platform 投递设备日志行（独立于 media/frame，避免与画面竞态）。"""

    lines: list[str] = Field(default_factory=list, max_length=200)


class ResourcePoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    is_default: bool = False
    enabled: bool = True


class ResourcePoolUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_default: Optional[bool] = None
    enabled: Optional[bool] = None


class ResourcePoolMemberIn(BaseModel):
    resource_id: str = Field(..., min_length=1, max_length=128)


class ResourcePoolProjectIn(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=128)


class ResourcePoolOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: str = ""
    is_default: bool = False
    enabled: bool = True
    runner_ids: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    can_manage: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class HeartbeatIn(BaseModel):
    runner_id: str
    # inventory 始终上报完整清单；devices 仅包含当前策略允许进入 TR 池的设备。
    inventory: list[DeviceInfo]
    devices: list[DeviceInfo]
    policy_revision: int = 0
    # 可选：心跳刷新本机能力；空列表表示保持注册时的 capabilities。
    capabilities: list[str] = Field(default_factory=list)
    host_backends: list[str] = Field(default_factory=list)


class ArtifactEntryOut(BaseModel):
    """制品内可勾选的执行入口（用例 / 套件 / 计划）。"""

    path: str = Field(..., description="相对工程根路径，如 TEST001.tc.yaml")
    kind: str = Field(..., description="case | suite | plan")
    name: str = ""


class JobCreate(BaseModel):
    """创建批跑：本地 project_dir 与/或已上传 artifact_id（至少其一）。"""

    name: str = "Suite"
    project_dir: str = ""
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    project_id: str = ""
    platform: str = "android"
    device_udids: list[str] = Field(
        default_factory=list,
        description="目标设备；空列表时任意空闲 Runner 可领取（可用 MC_REQUIRE_JOB_DEVICES=1 禁止）",
    )
    entry_paths: list[str] = Field(
        default_factory=list,
        description="要执行的相对路径（.tc/.ts/.tp）；空=发现全部用例",
    )
    parallel: bool = False
    parallel_workers: int = 0
    backend_mode: str = Field(
        default="auto",
        max_length=BACKEND_MODE_MAX_LEN,
        description="移动后端 / Web 浏览器 / HTTP 的 api_env profile",
    )
    web_engine: str = Field(
        default="selenium",
        description="platform=web 时：selenium|playwright（默认 selenium；不占用 backend_mode）",
    )
    wda_bundle: str = ""
    preferred_runner_id: Optional[str] = None
    webhook_url: str = Field(
        default="",
        description="可选；覆盖 MC_WEBHOOK_URL，任务终态 POST JSON",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="前置 Job id 列表；须全部 succeeded 后才可被 Runner claim（轻量线性 DAG）",
    )

    @model_validator(mode="after")
    def _need_source(self) -> JobCreate:
        if not (self.project_dir or "").strip() and not (self.artifact_id or "").strip():
            raise ValueError("project_dir or artifact_id required")
        p = (self.platform or "").strip().lower() or "android"
        if p not in JOB_PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(JOB_PLATFORMS)}")
        self.platform = p
        self.web_engine = normalize_web_engine(self.web_engine, p)
        apply_deviceless_run_target(self)
        self.backend_mode = normalize_stored_backend_mode(self.backend_mode)
        self.webhook_url = validate_webhook_url(self.webhook_url, resolve=False)
        deps: list[str] = []
        seen: set[str] = set()
        for x in self.depends_on or []:
            s = str(x or "").strip()
            if s and s not in seen:
                seen.add(s)
                deps.append(s)
        self.depends_on = deps
        return self


class JobOut(BaseModel):
    id: str
    name: str
    status: JobStatus
    project_dir: str
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    app_build_name: str = ""
    app_version_name: str = ""
    app_version_code: int = 0
    app_package_id: str = ""
    project_id: str = ""
    platform: str
    device_udids: list[str] = Field(default_factory=list)
    entry_paths: list[str] = Field(default_factory=list)
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
    depends_on: list[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # enqueue / 创建 Job 时可附带软提示（缺 Binding 等）；不影响入队成功
    warnings: list[str] = Field(default_factory=list)


class ArtifactPurgeOut(BaseModel):
    deleted: int = 0
    older_than_days: int = 0


class ReportPurgeOut(BaseModel):
    deleted: int = 0
    older_than_days: int = 0


class ReportIndex(BaseModel):
    report_path: str = ""
    passed: int = 0
    failed: int = 0
    total: int = 0
    duration_ms: int = 0
    summary: str = ""
    job_id: str = ""
    stored: bool = False  # 平台是否已存 HTML
    # 任务结档时冻结的版本维度（便于报告列表/对比筛）
    artifact_id: Optional[str] = None
    artifact_name: str = ""
    app_build_id: Optional[str] = None
    app_build_name: str = ""
    app_version_name: str = ""
    app_platform: str = ""
    job_name: str = ""
    project_id: str = ""
    platform: str = ""


class JobResultIn(BaseModel):
    """Runner 完成任务后回传。"""

    status: JobStatus = Field(..., description="succeeded | failed")
    error: Optional[str] = None
    report: Optional[ReportIndex] = None
    log: Optional[str] = Field(default=None, description="执行日志文本（可选，写入平台）")


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


UserCreateDuty = Literal[
    "user",
    "sys_admin",
    "org_member",
    "org_admin",
    "project_member",
    "project_owner",
    "project_viewer",
]
USER_CREATE_DUTIES = get_args(UserCreateDuty)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    duty: UserCreateDuty
    project_id: Optional[str] = Field(default=None, max_length=64)


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    role: Optional[str] = Field(default=None, description="admin | operator")
    disabled: Optional[bool] = None


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    disabled: bool = False
    created_at: Optional[datetime] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0  # access 有效秒数
    refresh_token: str = ""
    user: UserOut


class IdeHandoffOut(BaseModel):
    code: str
    expires_in: int = 1200


class IdeHandoffConsumeIn(BaseModel):
    code: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    """可空：浏览器走 HttpOnly Cookie（AUD-2026-02-C）；IDE 仍传 body。"""

    refresh_token: str = Field(default="", description="可选；空则读 mc_refresh Cookie")


class LogoutIn(BaseModel):
    refresh_token: str = ""


class ArtifactOut(BaseModel):
    id: str
    name: str
    filename: str
    size_bytes: int = 0
    uploaded_by: str = ""
    project_id: str = ""
    created_at: Optional[datetime] = None
    manifest_status: str = ""  # missing | valid | invalid
    manifest_version: str = ""
    required_runtime_version: str = ""
    manifest_warnings: list[str] = Field(default_factory=list)
    manifest_errors: list[str] = Field(default_factory=list)


class AppBuildOut(BaseModel):
    id: str
    name: str
    filename: str
    platform: str = ""
    version_name: str = ""
    version_code: int = 0
    size_bytes: int = 0
    sha256: str = ""
    package_id: str = ""
    main_activity: str = ""
    uploaded_by: str = ""
    project_id: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reused: bool = False  # True=sha256 命中既有记录，未重复落盘


class AppBuildUpdate(BaseModel):
    name: Optional[str] = None
    version_name: Optional[str] = None
    version_code: Optional[int] = None


class AppBuildPurgeOut(BaseModel):
    deleted: int = 0
    older_than_days: int = 0


class ProjectCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, description="空间 id，如 team-demo")
    name: str = ""
    description: str = ""
    org_id: str = ""  # 可选；缺省时用请求头 X-Org-Id


class ProjectOut(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    owner_user_id: str = ""
    org_id: str = ""
    created_at: Optional[datetime] = None
    # 当前登录用户在该项目中的角色：owner | member | viewer；平台 admin 为 owner（旁路）
    my_role: str = ""


class ProjectMemberIn(BaseModel):
    username: str = Field(..., min_length=1)
    role: str = "member"  # owner | member | viewer


class ProjectMemberOut(BaseModel):
    user_id: str
    username: str = ""
    role: str = "member"
    project_id: str = ""


class ProjectInviteCreate(BaseModel):
    role: str = "member"  # member | viewer
    label: str = ""
    expires_hours: int = Field(default=168, ge=0, le=24 * 365, description="0=不过期")
    max_uses: int = Field(default=0, ge=0, description="0=不限次数")


class OrganizationCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    name: str = ""
    description: str = ""


class OrganizationPolicies(BaseModel):
    """组织级权限开关。缺省全关：仅 owner/admin 可建项目、邀请成员。"""

    members_can_create_projects: bool = False
    members_can_invite: bool = False


class OrganizationPoliciesPatch(BaseModel):
    members_can_create_projects: Optional[bool] = None
    members_can_invite: Optional[bool] = None


class OrganizationOut(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    created_by: str = ""
    created_at: Optional[datetime] = None
    my_role: str = ""
    policies: OrganizationPolicies = Field(default_factory=OrganizationPolicies)


class OrganizationMemberIn(BaseModel):
    username: str = Field(..., min_length=1)
    role: str = "member"  # owner | admin | member


class OrganizationMemberOut(BaseModel):
    user_id: str
    username: str = ""
    role: str = "member"
    org_id: str = ""


class ProjectInviteOut(BaseModel):
    id: str
    project_id: str
    token: str
    role: str = "member"
    label: str = ""
    created_by: str = ""
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    max_uses: int = 0
    use_count: int = 0
    revoked: bool = False
    invite_path: str = ""


class ProjectInvitePreview(BaseModel):
    token: str
    project_id: str
    project_name: str = ""
    role: str = "member"
    label: str = ""
    expires_at: Optional[datetime] = None
    valid: bool = True
    detail: str = ""


class InviteRegisterIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


class AclGrantIn(BaseModel):
    resource_type: str = Field(..., description="artifact | job | schedule | app_build")
    resource_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    permission: str = Field(default="read", description="read | write")


class AclGrantOut(BaseModel):
    id: str
    resource_type: str
    resource_id: str
    user_id: str
    username: str = ""
    permission: str = "read"
    created_at: Optional[datetime] = None


class AuditOut(BaseModel):
    id: str
    action: str
    actor: str = ""
    actor_kind: str = ""
    resource_type: str = ""
    resource_id: str = ""
    org_id: str = ""
    detail: str = ""
    created_at: Optional[datetime] = None


class ScheduleCreate(BaseModel):
    """创建批跑计划（字段对齐桌面 Schedule + Job 模板）。"""

    name: str = "Schedule"
    project_dir: str = ""
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    project_id: str = ""
    platform: str = "android"
    device_udids: list[str] = Field(default_factory=list)
    parallel: bool = False
    parallel_workers: int = 0
    backend_mode: str = Field(default="auto", max_length=BACKEND_MODE_MAX_LEN)
    web_engine: str = Field(
        default="selenium",
        description="platform=web 时：selenium|playwright",
    )
    wda_bundle: str = ""
    preferred_runner_id: Optional[str] = None
    webhook_url: str = ""
    delay_sec: int = Field(0, ge=0)
    interval_sec: int = Field(0, ge=0)
    repeat: int = Field(1, ge=0, description="总次数；0=不限")
    stop_on_fail: bool = False
    enabled: bool = True
    entry_paths: list[str] = Field(
        default_factory=list,
        description="要执行的相对路径；空=发现全部用例",
    )

    @model_validator(mode="after")
    def _need_source(self) -> ScheduleCreate:
        if not (self.project_dir or "").strip() and not (self.artifact_id or "").strip():
            raise ValueError("请提供 project_dir 或 artifact_id。")
        p = (self.platform or "").strip().lower() or "android"
        if p not in JOB_PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(JOB_PLATFORMS)}")
        self.platform = p
        self.web_engine = normalize_web_engine(self.web_engine, p)
        apply_deviceless_run_target(self)
        self.backend_mode = normalize_stored_backend_mode(self.backend_mode)
        self.webhook_url = validate_webhook_url(self.webhook_url, resolve=False)
        return self


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    project_dir: Optional[str] = None
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    project_id: Optional[str] = None
    platform: Optional[str] = None
    device_udids: Optional[list[str]] = None
    parallel: Optional[bool] = None
    parallel_workers: Optional[int] = None
    backend_mode: Optional[str] = Field(default=None, max_length=BACKEND_MODE_MAX_LEN)
    web_engine: Optional[str] = None
    wda_bundle: Optional[str] = None
    preferred_runner_id: Optional[str] = None
    webhook_url: Optional[str] = None
    delay_sec: Optional[int] = Field(None, ge=0)
    interval_sec: Optional[int] = Field(None, ge=0)
    repeat: Optional[int] = Field(None, ge=0)
    stop_on_fail: Optional[bool] = None
    entry_paths: Optional[list[str]] = None

    @model_validator(mode="after")
    def _norm_platform(self) -> ScheduleUpdate:
        if self.platform is not None:
            p = self.platform.strip().lower() or "android"
            if p not in JOB_PLATFORMS:
                raise ValueError(f"platform must be one of {sorted(JOB_PLATFORMS)}")
            self.platform = p
        if self.webhook_url is not None:
            self.webhook_url = validate_webhook_url(self.webhook_url, resolve=False)
        if self.web_engine is not None:
            plat = self.platform
            eng = (self.web_engine or "selenium").strip().lower()
            if eng not in ("selenium", "playwright"):
                raise ValueError("web_engine must be selenium or playwright")
            self.web_engine = eng if (plat or "").strip().lower() == "web" else "selenium"
        if self.backend_mode is not None:
            self.backend_mode = normalize_stored_backend_mode(self.backend_mode)
        return self


class ScheduleOut(BaseModel):
    id: str
    name: str
    enabled: bool
    project_dir: str = ""
    artifact_id: Optional[str] = None
    app_build_id: Optional[str] = None
    app_build_name: str = ""
    app_version_name: str = ""
    app_version_code: int = 0
    app_package_id: str = ""
    project_id: str = ""
    platform: str = "android"
    device_udids: list[str] = Field(default_factory=list)
    parallel: bool = False
    parallel_workers: int = 0
    backend_mode: str = "auto"
    web_engine: str = "selenium"
    wda_bundle: str = ""
    preferred_runner_id: Optional[str] = None
    webhook_url: str = ""
    delay_sec: int = 0
    interval_sec: int = 0
    repeat: int = 1
    stop_on_fail: bool = False
    entry_paths: list[str] = Field(default_factory=list)
    runs_done: int = 0
    next_run_at: Optional[datetime] = None
    last_job_id: Optional[str] = None
    last_passed: Optional[bool] = None
    created_by: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ListPageMeta(BaseModel):
    """列表分页元数据（运维 / 设计域共用字段名）。"""

    total: int = 0
    page: int = 1
    page_size: int = 20


class ProjectListPage(ListPageMeta):
    items: list[ProjectOut] = Field(default_factory=list)


class ProjectMemberListPage(ListPageMeta):
    items: list[ProjectMemberOut] = Field(default_factory=list)


class OrganizationMemberListPage(ListPageMeta):
    items: list[OrganizationMemberOut] = Field(default_factory=list)


class OrganizationListPage(ListPageMeta):
    items: list[OrganizationOut] = Field(default_factory=list)


class DeviceListPage(ListPageMeta):
    items: list[dict[str, Any]] = Field(default_factory=list)


class JobListPage(ListPageMeta):
    items: list[JobOut] = Field(default_factory=list)


class ScheduleListPage(ListPageMeta):
    items: list[ScheduleOut] = Field(default_factory=list)


class RunnerListPage(ListPageMeta):
    items: list[RunnerOut] = Field(default_factory=list)


class UserListPage(ListPageMeta):
    items: list[UserOut] = Field(default_factory=list)


class ReportListPage(ListPageMeta):
    items: list[ReportIndex] = Field(default_factory=list)


class ArtifactListPage(ListPageMeta):
    items: list[ArtifactOut] = Field(default_factory=list)


class AppBuildListPage(ListPageMeta):
    items: list[AppBuildOut] = Field(default_factory=list)


class AuditListPage(ListPageMeta):
    items: list[AuditOut] = Field(default_factory=list)


class ResourcePoolListPage(ListPageMeta):
    items: list[ResourcePoolOut] = Field(default_factory=list)


class ProjectInviteListPage(ListPageMeta):
    items: list[ProjectInviteOut] = Field(default_factory=list)


class AclGrantListPage(ListPageMeta):
    items: list[AclGrantOut] = Field(default_factory=list)


class DeviceReservationListPage(ListPageMeta):
    items: list[DeviceReservationOut] = Field(default_factory=list)
