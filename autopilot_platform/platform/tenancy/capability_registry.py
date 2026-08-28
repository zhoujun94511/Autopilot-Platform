"""RBAC 能力 ↔ API 路由绑定注册表（ARCH-002 最小步）。

真源：AutoPilot/docs/rbac-capability-matrix.md
用途：防止 OpenAPI 路由守卫与能力矩阵漂移；供契约测试扫描 FastAPI 路由。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GuardKind = Literal[
    "platform_admin",  # is_platform_admin / User.role=admin
    "org_admin",  # org owner/admin（本 org）
    "project_write",  # project owner/member 或 platform admin
    "project_read",  # project member/viewer 或 platform admin
    "authenticated",  # 任意已登录用户
    "runner",  # Runner Token
]

# 与 rbac-capability-matrix.md §2 一致
CAPABILITY_IDS: frozenset[str] = frozenset(
    {
        "cap.jobs.create",
        "cap.jobs.cancel",
        "cap.jobs.retry",
        "cap.artifacts.upload",
        "cap.artifacts.purge",
        "cap.app_builds.upload",
        "cap.app_builds.purge",
        "cap.reports.view",
        "cap.reports.purge",
        "cap.devices.view",
        "cap.devices.release",
        "cap.devices.reserve",
        "cap.devices.remote",
        "cap.devices.maintenance",
        "cap.runners.view",
        "cap.runners.issue_token",
        "cap.runners.deregister",
        "cap.runners.reclaim",
        "cap.runners.managed",
        "cap.share.read",
        "cap.share.write",
        "cap.ops.config",
        "cap.ops.view_budget",
        "cap.ops.ai.codegen",
        "cap.audit.view",
        "cap.users.manage",
        "cap.design.edit",
        "cap.ide.runner.start_scoped",
    }
)


@dataclass(frozen=True)
class RouteCapabilityBinding:
    capability_id: str
    method: str
    path: str  # OpenAPI 路径，含 /api/v1 前缀；{param} 占位
    guard: GuardKind
    note: str = ""


# 关键路由 — 变更守卫时须同步矩阵文档与本表
CAPABILITY_ROUTE_BINDINGS: tuple[RouteCapabilityBinding, ...] = (
    RouteCapabilityBinding(
        "cap.ide.runner.start_scoped",
        "POST",
        "/api/v1/runners/{runner_id}/scoped-token",
        "platform_admin",
        "IDE Operator 403；仅平台 admin 代签",
    ),
    RouteCapabilityBinding(
        "cap.runners.issue_token",
        "POST",
        "/api/v1/runners/{runner_id}/token",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.runners.deregister",
        "DELETE",
        "/api/v1/runners/{runner_id}",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.runners.view",
        "GET",
        "/api/v1/runners",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.runners.managed",
        "GET",
        "/api/v1/runners/managed",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.devices.view",
        "GET",
        "/api/v1/devices",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.view",
        "GET",
        "/api/v1/devices/board",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.share.read",
        "GET",
        "/api/v1/acl",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.share.write",
        "POST",
        "/api/v1/acl",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.share.write",
        "DELETE",
        "/api/v1/acl/{acl_id}",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.ops.view_budget",
        "GET",
        "/api/v1/design/stats",
        "authenticated",
        "响应裁剪：非 admin 无 tokens 字段",
    ),
    RouteCapabilityBinding(
        "cap.ops.view_budget",
        "GET",
        "/api/v1/ops/agentops",
        "authenticated",
        "响应裁剪：非 admin 无 tokens 字段",
    ),
    RouteCapabilityBinding(
        "cap.reports.view",
        "GET",
        "/api/v1/ops/job-quality",
        "authenticated",
        "项目作用域 Job 失败趋势 / fail_reason",
    ),
    RouteCapabilityBinding(
        "cap.ops.ai.codegen",
        "POST",
        "/api/v1/ops/ai/codegen",
        "authenticated",
        "链路 3 IDE 网关；厂商 Key 仅服务端；须计费作用域",
    ),
    RouteCapabilityBinding(
        "cap.ops.config",
        "GET",
        "/api/v1/ops/summary",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.audit.view",
        "GET",
        "/api/v1/audit",
        "org_admin",
        "org 范围；platform admin 全平台",
    ),
    RouteCapabilityBinding(
        "cap.users.manage",
        "GET",
        "/api/v1/auth/users",
        "org_admin",
    ),
    RouteCapabilityBinding(
        "cap.artifacts.purge",
        "POST",
        "/api/v1/artifacts/purge",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.app_builds.purge",
        "POST",
        "/api/v1/app-builds/purge",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.reports.purge",
        "POST",
        "/api/v1/reports/purge",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.design.edit",
        "POST",
        "/api/v1/design/requirements",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.jobs.create",
        "POST",
        "/api/v1/jobs",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.jobs.cancel",
        "POST",
        "/api/v1/jobs/{job_id}/cancel",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.jobs.retry",
        "POST",
        "/api/v1/jobs/{job_id}/retry",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.runners.reclaim",
        "POST",
        "/api/v1/jobs/reclaim",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.devices.release",
        "POST",
        "/api/v1/devices/{udid}/release",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.devices.maintenance",
        "POST",
        "/api/v1/devices/{udid}/maintenance",
        "platform_admin",
    ),
    RouteCapabilityBinding(
        "cap.devices.reserve",
        "GET",
        "/api/v1/device-reservations",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.reserve",
        "POST",
        "/api/v1/devices/{device_id}/reservations",
        "authenticated",
        "服务层校验 can_user_use_device",
    ),
    RouteCapabilityBinding(
        "cap.devices.reserve",
        "DELETE",
        "/api/v1/device-reservations/{reservation_id}",
        "authenticated",
        "占用人或 platform admin",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/devices/{device_id}/remote-sessions",
        "authenticated",
        "占用人或 platform admin；busy_kind=job 拒绝",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/devices/{device_id}/remote-sessions/join",
        "authenticated",
        "组织/平台管理员旁观他人远控；占用人 join 保持 controller",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/participants",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/participants",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "DELETE",
        "/api/v1/device-remote-sessions/{session_id}/participants/{participant_id}",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/participants/{participant_id}/promote",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/commands",
        "authenticated",
        "viewer 仅只读命令",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/logs/stream-token",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/logs/stream",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/ws",
        "authenticated",
        "远控 WebSocket；Runner 用 Token，browser 首帧鉴权",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "DELETE",
        "/api/v1/device-remote-sessions/{session_id}",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/offer",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/answer",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/ice",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/signaling-poll",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/media",
        "authenticated",
        "MJPEG frame / 触控 input（与 SDP 队列隔离）",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/media-poll",
        "authenticated",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/runners/me/remote-commands",
        "runner",
        "Runner 拉取 pending 远控会话",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "GET",
        "/api/v1/runners/me/remote-prewarm-hints",
        "runner",
        "Runner 占用后 soft prewarm 提示",
    ),
    RouteCapabilityBinding(
        "cap.devices.remote",
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/runner-status",
        "runner",
    ),
    RouteCapabilityBinding(
        "cap.artifacts.upload",
        "POST",
        "/api/v1/artifacts",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.app_builds.upload",
        "POST",
        "/api/v1/app-builds",
        "project_write",
    ),
    RouteCapabilityBinding(
        "cap.reports.view",
        "GET",
        "/api/v1/jobs/{job_id}/report",
        "project_read",
    ),
)
