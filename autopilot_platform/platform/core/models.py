"""ORM 表：users / artifacts / runners / devices / jobs / reports。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TypeVar, cast

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .db import Base

RowT = TypeVar("RowT")


def db_get(db: Session, model: type[RowT], ident: object) -> RowT | None:
    """``Session.get`` 包装：让类型检查器得到 ``RowT | None`` 而非 ``type[RowT]``。"""
    return cast(RowT | None, db.get(model, ident))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_oidc_sub",
            "oidc_sub",
            unique=True,
            sqlite_where=text("oidc_sub != ''"),
            postgresql_where=text("oidc_sub != ''"),
        ),
        Index(
            "uq_users_saml_nameid",
            "saml_nameid",
            unique=True,
            sqlite_where=text("saml_nameid != ''"),
            postgresql_where=text("saml_nameid != ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(32), default="operator")  # admin | operator
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    oidc_sub: Mapped[str] = mapped_column(String(256), default="")  # IdP subject
    saml_nameid: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrganizationRow(Base):
    """企业内组织 / 事业部（软多租户上层）。"""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 组织级开关 JSON，缺省 {}；键见 organizations.parse_org_policies
    policies_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class OrganizationMemberRow(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_member_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(128), ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")  # owner | admin | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # 业务空间 id
    name: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    org_id: Mapped[str] = mapped_column(String(128), default="", index=True)  # 所属组织，创建时必填
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMemberRow(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")  # owner | member | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectInviteRow(Base):
    """项目邀请令牌：链接邀请 + 自助注册入项。"""

    __tablename__ = "project_invites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")  # member | viewer
    label: Mapped[str] = mapped_column(String(256), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0=不限
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RefreshTokenRow(Base):
    """不透明 refresh token（仅存哈希，可吊销）。"""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    replaced_by: Mapped[str] = mapped_column(String(64), default="")  # 轮换后的新 token id


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256), default="")
    filename: Mapped[str] = mapped_column(String(512), default="")
    stored_path: Mapped[str] = mapped_column(Text, default="")  # zip 路径
    extract_path: Mapped[str] = mapped_column(Text, default="")  # 解压根（同机 Runner 可用）
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    project_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    manifest_status: Mapped[str] = mapped_column(String(32), default="")  # missing|valid|invalid
    manifest_version: Mapped[str] = mapped_column(String(64), default="")
    manifest_notes_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppBuildRow(Base):
    """应用安装包资源（apk/ipa），与工程制品分域存储。"""

    __tablename__ = "app_builds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256), default="")  # 展示名，可重命名
    filename: Mapped[str] = mapped_column(String(512), default="")
    platform: Mapped[str] = mapped_column(String(32), default="", index=True)  # android | ios
    version_name: Mapped[str] = mapped_column(String(128), default="")
    version_code: Mapped[int] = mapped_column(Integer, default=0)
    stored_path: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    package_id: Mapped[str] = mapped_column(String(256), default="")  # package / bundle id
    main_activity: Mapped[str] = mapped_column(String(512), default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    project_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourcePoolRow(Base):
    """组织内 Runner / Device 软隔离池。"""

    __tablename__ = "resource_pools"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_resource_pool_org_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourcePoolRunnerRow(Base):
    __tablename__ = "resource_pool_runners"
    __table_args__ = (
        UniqueConstraint("pool_id", "runner_id", name="uq_resource_pool_runner"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    pool_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("resource_pools.id", ondelete="CASCADE"), index=True
    )
    runner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("runners.runner_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourcePoolDeviceRow(Base):
    __tablename__ = "resource_pool_devices"
    __table_args__ = (
        UniqueConstraint("pool_id", "device_id", name="uq_resource_pool_device"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    pool_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("resource_pools.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourcePoolProjectRow(Base):
    __tablename__ = "resource_pool_projects"
    __table_args__ = (
        UniqueConstraint("pool_id", "project_id", name="uq_resource_pool_project"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    pool_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("resource_pools.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunnerRow(Base):
    __tablename__ = "runners"

    runner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[str] = mapped_column(String(64), default="")
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(128), default="", index=True)  # sha256 hex
    # Token / 节点作用域：空=不限制（兼容旧部署）；设置后 claim 仅本 org / 项目列表
    org_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    project_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    owner_user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    # ide=用户 IDE 注册（私有）；platform/managed=平台共享。空值按 platform 兼容。
    registration_source: Mapped[str] = mapped_column(
        String(32), default="platform", index=True
    )
    # Runner 发现的完整本机设备清单与 Web 选择策略分离：
    # inventory 允许展示“未注册候选”，DeviceRow 只保留实际进入 TR 池的设备。
    device_inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    device_selection_mode: Mapped[str] = mapped_column(
        String(16), default="all", index=True
    )
    selected_device_udids_json: Mapped[str] = mapped_column(Text, default="[]")
    device_policy_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    devices: Mapped[list[DeviceRow]] = relationship(
        "DeviceRow", back_populates="runner", cascade="all, delete-orphan"
    )

    @property
    def capabilities(self) -> list[str]:
        try:
            return list(json.loads(self.capabilities_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @capabilities.setter
    def capabilities(self, value: list[str]) -> None:
        self.capabilities_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def project_ids(self) -> list[str]:
        try:
            raw = json.loads(self.project_ids_json or "[]")
            return [str(x).strip() for x in raw if str(x).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @project_ids.setter
    def project_ids(self, value: list[str]) -> None:
        cleaned = [str(x).strip() for x in (value or []) if str(x).strip()]
        # 去重保序
        seen: set[str] = set()
        out: list[str] = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                out.append(p)
        self.project_ids_json = json.dumps(out, ensure_ascii=False)

    @property
    def device_inventory(self) -> list[dict]:
        try:
            raw = json.loads(self.device_inventory_json or "[]")
            return [dict(x) for x in raw if isinstance(x, dict)]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @device_inventory.setter
    def device_inventory(self, value: list[dict]) -> None:
        self.device_inventory_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def selected_device_udids(self) -> list[str]:
        try:
            raw = json.loads(self.selected_device_udids_json or "[]")
            return list(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @selected_device_udids.setter
    def selected_device_udids(self, value: list[str]) -> None:
        cleaned = list(
            dict.fromkeys(str(x).strip() for x in (value or []) if str(x).strip())
        )
        self.selected_device_udids_json = json.dumps(cleaned, ensure_ascii=False)


class DeviceRow(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("runner_id", "udid", name="uq_device_runner_udid"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    runner_id: Mapped[str] = mapped_column(String(128), ForeignKey("runners.runner_id"), index=True)
    udid: Mapped[str] = mapped_column(String(256), index=True)
    platform: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(256), default="")
    model: Mapped[str] = mapped_column(String(256), default="")
    os_version: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(32), default="ready")
    backends_json: Mapped[str] = mapped_column(Text, default="[]")
    health_note: Mapped[str] = mapped_column(String(512), default="")
    labels_json: Mapped[str] = mapped_column(Text, default="[]")
    busy_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 与 busy_job_id 共用同一 Device 行做条件 UPDATE，保证预约/任务领取互斥。
    reservation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 管理员维护态：True 时该物理设备不参与调度（与 Runner 上报的 state 分离，心跳不覆盖）
    admin_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runner: Mapped[RunnerRow] = relationship("RunnerRow", back_populates="devices")

    @property
    def labels(self) -> list[str]:
        try:
            return list(json.loads(self.labels_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @labels.setter
    def labels(self, value: list[str]) -> None:
        self.labels_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def backends(self) -> list[str]:
        try:
            return list(json.loads(self.backends_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @backends.setter
    def backends(self, value: list[str]) -> None:
        self.backends_json = json.dumps(list(value or []), ensure_ascii=False)


class DeviceReservationRow(Base):
    """用户在 Job 之外预占设备的限时租约。"""

    __tablename__ = "device_reservations"
    __table_args__ = (
        Index(
            "uq_device_reservation_active",
            "device_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(64), default="", index=True)
    reason: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeviceRemoteSessionRow(Base):
    """浏览器远控会话（绑定设备占用；与 reservation 生命周期解耦关闭）。"""

    __tablename__ = "device_remote_sessions"
    __table_args__ = (
        Index(
            "uq_device_remote_session_active",
            "device_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'ready', 'connected')"),
            postgresql_where=text("status IN ('pending', 'ready', 'connected')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    runner_id: Mapped[str] = mapped_column(String(128), index=True)
    udid: Mapped[str] = mapped_column(String(256), default="")
    platform: Mapped[str] = mapped_column(String(64), default="")
    reservation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    # pending → ready → connected → closed|failed
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str] = mapped_column(String(512), default="")
    max_viewers: Mapped[int] = mapped_column(Integer, default=5)
    # 信令中继：JSON 队列（offer/answer/ice），体量小，MVP 存 DB
    signaling_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def capabilities(self) -> list[str]:
        try:
            return list(json.loads(self.capabilities_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @capabilities.setter
    def capabilities(self, value: list[str]) -> None:
        self.capabilities_json = json.dumps(list(value or []), ensure_ascii=False)


class DeviceRemoteParticipantRow(Base):
    """远控主会话参与者：唯一 controller + 多只读 viewer。"""

    __tablename__ = "device_remote_participants"
    __table_args__ = (
        Index(
            "ix_device_remote_participant_session_status",
            "session_id",
            "status",
        ),
        Index(
            "uq_device_remote_participant_connection",
            "session_id",
            "connection_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("device_remote_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(32), default="viewer", index=True)
    connection_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="joining", index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created_at", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256), default="Suite")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    project_dir: Mapped[str] = mapped_column(Text, default="")
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    app_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    platform: Mapped[str] = mapped_column(String(64), default="android")
    device_udids_json: Mapped[str] = mapped_column(Text, default="[]")
    entry_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    parallel: Mapped[bool] = mapped_column(Boolean, default=False)
    parallel_workers: Mapped[int] = mapped_column(Integer, default=0)
    backend_mode: Mapped[str] = mapped_column(String(64), default="auto")
    web_engine: Mapped[str] = mapped_column(String(32), default="selenium")
    wda_bundle: Mapped[str] = mapped_column(String(256), default="")
    preferred_runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str] = mapped_column(Text, default="")
    parent_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # E2：轻量线性依赖（前置 Job id 列表，须全部 succeeded 才可 claim）
    depends_on_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(64), default="")  # username
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[ReportRow | None] = relationship(
        "ReportRow", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def device_udids(self) -> list[str]:
        try:
            return list(json.loads(self.device_udids_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @device_udids.setter
    def device_udids(self, value: list[str]) -> None:
        self.device_udids_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def entry_paths(self) -> list[str]:
        try:
            return [str(x) for x in json.loads(self.entry_paths_json or "[]")]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @entry_paths.setter
    def entry_paths(self, value: list[str]) -> None:
        cleaned = []
        for x in value or []:
            s = str(x or "").strip().replace("\\", "/")
            if s:
                cleaned.append(s)
        self.entry_paths_json = json.dumps(cleaned, ensure_ascii=False)

    @property
    def depends_on(self) -> list[str]:
        try:
            return [str(x).strip() for x in json.loads(self.depends_on_json or "[]") if str(x).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @depends_on.setter
    def depends_on(self, value: list[str]) -> None:
        ids: list[str] = []
        seen: set[str] = set()
        for x in value or []:
            s = str(x or "").strip()
            if s and s not in seen:
                seen.add(s)
                ids.append(s)
        self.depends_on_json = json.dumps(ids, ensure_ascii=False)


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id"), unique=True, index=True)
    report_path: Mapped[str] = mapped_column(Text, default="")
    stored_path: Mapped[str] = mapped_column(Text, default="")  # 平台侧 HTML 路径
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    # 结档时从 Job/制品/应用资源冻结，避免后续重命名导致历史报告失真
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact_name: Mapped[str] = mapped_column(String(256), default="")
    app_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    app_build_name: Mapped[str] = mapped_column(String(256), default="")
    app_version_name: Mapped[str] = mapped_column(String(128), default="")
    app_platform: Mapped[str] = mapped_column(String(32), default="")
    result_json_path: Mapped[str] = mapped_column(Text, default="")  # 平台侧 result.json
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[JobRow] = relationship("JobRow", back_populates="report")


class ScheduleRow(Base):
    """平台侧批跑计划：到期后自动创建 Job。"""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(256), default="Schedule")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    project_dir: Mapped[str] = mapped_column(Text, default="")
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    app_build_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    platform: Mapped[str] = mapped_column(String(64), default="android")
    device_udids_json: Mapped[str] = mapped_column(Text, default="[]")
    parallel: Mapped[bool] = mapped_column(Boolean, default=False)
    parallel_workers: Mapped[int] = mapped_column(Integer, default=0)
    backend_mode: Mapped[str] = mapped_column(String(64), default="auto")
    web_engine: Mapped[str] = mapped_column(String(32), default="selenium")
    wda_bundle: Mapped[str] = mapped_column(String(256), default="")
    preferred_runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    webhook_url: Mapped[str] = mapped_column(Text, default="")
    delay_sec: Mapped[int] = mapped_column(Integer, default=0)
    interval_sec: Mapped[int] = mapped_column(Integer, default=0)
    repeat: Mapped[int] = mapped_column(Integer, default=1)  # 0=不限
    stop_on_fail: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    runs_done: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def device_udids(self) -> list[str]:
        try:
            return list(json.loads(self.device_udids_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @device_udids.setter
    def device_udids(self, value: list[str]) -> None:
        self.device_udids_json = json.dumps(list(value or []), ensure_ascii=False)

    @property
    def entry_paths(self) -> list[str]:
        try:
            return list(json.loads(self.entry_paths_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @entry_paths.setter
    def entry_paths(self, value: list[str]) -> None:
        self.entry_paths_json = json.dumps(list(value or []), ensure_ascii=False)


class ResourceAclRow(Base):
    """资源级分享：无 project_id 时默认仅创建者可见，可显式授权给其他用户。"""

    __tablename__ = "resource_acl"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)  # artifact|job|schedule|app_build
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    permission: Mapped[str] = mapped_column(String(16), default="read")  # read|write
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLogRow(Base):
    """关键操作审计。"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(64), index=True, default="")
    actor: Mapped[str] = mapped_column(String(128), default="", index=True)
    actor_kind: Mapped[str] = mapped_column(String(32), default="")  # user|runner|system
    resource_type: Mapped[str] = mapped_column(String(32), default="")
    resource_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    org_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OpsLockRow(Base):
    """跨进程运维锁（如 schedule_loop leader lease）。"""

    __tablename__ = "ops_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(256), default="")
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginRateRow(Base):
    """登录失败限速桶（跨进程 / 多 worker 共享）。"""

    __tablename__ = "login_rate_buckets"

    rate_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    failures_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
