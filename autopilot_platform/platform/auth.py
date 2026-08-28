"""鉴权：Runner 用 X-API-Token（全局或 Runner 独立令牌）；管理台用户用 Bearer JWT。"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status
# noinspection PyPackageRequirements
from jwt import PyJWTError
# noinspection PyPackageRequirements
from sqlalchemy import select
# noinspection PyPackageRequirements
from sqlalchemy.orm import Session

from .core.db import get_session
from .core.models import ProjectRow, RunnerRow, UserRow, db_get
from .core.security import decode_access_token
from .core.settings import (
    admin_api_token,
    allow_legacy_token_admin,
    api_token,
    is_production,
)
from .core import api_messages as msg


@dataclass
class AuthContext:
    """请求身份：runner_token 或已登录用户。"""

    kind: str  # "runner" | "user"
    username: str = ""
    user_id: str = ""
    role: str = ""
    runner_id: str = ""  # 独立 Runner Token 时绑定
    stream_job_id: str = ""
    stream_session_id: str = ""
    org_id: str = ""  # 当前组织上下文（X-Org-Id）或 Runner 绑定 org
    # Runner 作用域：空元组=不限制；非空则 claim 仅允许这些 project_id
    project_ids: tuple[str, ...] = ()


def is_platform_admin(auth: AuthContext) -> bool:
    """仅用户 admin 或显式运维令牌（AuthContext.role=admin）。

    独立 Runner Token 与「仅作执行通道」的全局 MC_API_TOKEN（role=runner）都不是管理员。
    放在本模块避免 ``auth ↔ tenancy.projects`` 为这一行判断互相延迟 import。
    """
    return (auth.role or "") == "admin"


def is_ops_admin(auth: AuthContext) -> bool:
    """运维配置写权限（``/ops/*`` 热更新等）。

    当前等同 ``is_platform_admin``；预留独立 ``ops_admin`` 平台角色扩展点，
    日后可写 ops 配置但不等于删用户 / 跨租户。暂勿半吊子改登录角色枚举。
    """
    return is_platform_admin(auth)


def hash_api_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _token_match(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def auth_from_jwt(token: str, db: Session) -> AuthContext:
    """解析 JWT（Authorization Bearer）为用户上下文。"""
    try:
        payload = decode_access_token(token)
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_INVALID_TOKEN,
        ) from exc
    if payload.get("typ") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_INVALID_TOKEN,
        )
    uid = str(payload.get("sub") or "")
    user = db_get(db, UserRow, uid) if uid else None
    if user is None or user.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_USER_DISABLED,
        )
    return AuthContext(
        kind="user",
        username=str(user.username),
        user_id=str(user.id),
        role=str(user.role or "operator"),
        stream_job_id=(
            str(payload.get("job_id") or "")
            if payload.get("purpose") == "job_log_stream"
            else ""
        ),
    )


def require_stream_auth(
    access_token: Annotated[str, Query(min_length=1)],
) -> AuthContext:
    """仅接受短时日志流令牌（EventSource 用 Query，勿传普通 access JWT）。

    支持 ``job_log_stream``（任务日志）与 ``device_log_stream``（远控设备日志）。
    """
    try:
        payload = decode_access_token(access_token.strip())
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_INVALID_TOKEN,
        ) from exc
    typ = str(payload.get("typ") or "")
    purpose = str(payload.get("purpose") or "")
    job_id = str(payload.get("job_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if typ == "job_log_stream" and purpose == "job_log_stream" and job_id:
        return AuthContext(
            kind="user",
            username=str(payload.get("username") or ""),
            user_id=str(payload.get("sub") or ""),
            role=str(payload.get("role") or "operator"),
            stream_job_id=job_id,
        )
    if typ == "device_log_stream" and purpose == "device_log_stream" and session_id:
        return AuthContext(
            kind="user",
            username=str(payload.get("username") or ""),
            user_id=str(payload.get("sub") or ""),
            role=str(payload.get("role") or "operator"),
            stream_session_id=session_id,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=msg.AUTH_INVALID_TOKEN,
    )


def auth_from_device_remote_token(token: str, session_id: str) -> AuthContext:
    """校验绑定单一远控会话的短时票，供 WebSocket handshake 使用。"""
    try:
        payload = decode_access_token((token or "").strip())
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_INVALID_TOKEN,
        ) from exc
    if (
        payload.get("typ") != "device_remote"
        or payload.get("purpose") != "device_remote"
        or str(payload.get("session_id") or "") != session_id
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg.AUTH_INVALID_TOKEN,
        )
    return AuthContext(
        kind="user",
        username=str(payload.get("username") or ""),
        user_id=str(payload.get("sub") or ""),
        role=str(payload.get("role") or "operator"),
    )


def auth_runner_api_token(raw_token: str, db: Session) -> AuthContext:
    """WebSocket 版 Runner Token 校验；语义与 ``require_auth`` 保持一致。"""
    token = (raw_token or "").strip()
    if _token_match(token, admin_api_token()):
        return AuthContext(kind="runner", username="ops", role="admin")
    if _token_match(token, api_token()):
        return AuthContext(kind="runner", username="runner", role="runner")
    if token:
        row = db.scalars(
            select(RunnerRow).where(RunnerRow.token_hash == hash_api_token(token))
        ).first()
        if row is not None:
            return AuthContext(
                kind="runner",
                username=row.runner_id,
                role="runner",
                runner_id=row.runner_id,
                org_id=(getattr(row, "org_id", None) or "").strip(),
                project_ids=tuple(getattr(row, "project_ids", None) or ()),
            )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=msg.AUTH_INVALID_TOKEN,
    )


def require_auth(
    request: Request,
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
    access_token: Annotated[
        str | None,
        Query(
            include_in_schema=False,
            description="仅 */logs/stream：短时 job_log_stream / device_log_stream 票（EventSource）",
        ),
    ] = None,
    db: Session = Depends(get_session),
) -> AuthContext:
    # 显式运维令牌（MC_ADMIN_API_TOKEN）：等同平台管理员通道
    admin_tok = admin_api_token()
    if _token_match(x_api_token, admin_tok):
        return AuthContext(kind="runner", username="ops", role="admin", org_id=(x_org_id or "").strip())

    expected = api_token()
    if _token_match(x_api_token, expected):
        # 已配置 MC_ADMIN_API_TOKEN → 本令牌仅为执行通道。
        # 未配置时默认仍为 runner；仅显式 MC_ALLOW_LEGACY_TOKEN_ADMIN=1 才升 admin。
        if admin_tok:
            role = "runner"
        elif allow_legacy_token_admin():
            role = "admin"
        else:
            role = "runner"
        return AuthContext(kind="runner", username="runner", role=role, org_id=(x_org_id or "").strip())

    if x_api_token:
        th = hash_api_token(x_api_token)
        row = db.scalars(select(RunnerRow).where(RunnerRow.token_hash == th)).first()
        if row is not None:
            return AuthContext(
                kind="runner",
                username=row.runner_id,
                role="runner",
                runner_id=row.runner_id,
                org_id=(getattr(row, "org_id", None) or "").strip() or (x_org_id or "").strip(),
                project_ids=tuple(getattr(row, "project_ids", None) or ()),
            )

    if authorization and authorization.lower().startswith("bearer "):
        jwt_raw = authorization[7:].strip()
        ctx = auth_from_jwt(jwt_raw, db)
        oid = (x_org_id or "").strip()
        if not oid:
            try:
                payload = decode_access_token(jwt_raw)
                oid = str(payload.get("org_id") or "").strip()
            except (PyJWTError, ValueError, TypeError, KeyError):
                oid = ""
        if oid:
            from .tenancy.organizations import assert_can_access_org  # 延迟：organizations 顶栏 import projects

            if not is_platform_admin(ctx):
                try:
                    assert_can_access_org(db, ctx, oid)
                except PermissionError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
                    ) from exc
            ctx.org_id = oid
        return ctx

    # 父路由全局 Depends(require_auth)：SSE EventSource 只能带 Query。
    # 仅 /logs/stream 接受短时票；禁止把普通用户 JWT 放进任意 API 的 Query。
    path = (request.url.path or "").rstrip("/")
    if access_token and path.endswith("/logs/stream"):
        return require_stream_auth(access_token.strip())

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=msg.AUTH_REQUIRED,
    )


def require_admin(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    if is_platform_admin(auth):
        return auth
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg.AUTH_ADMIN_REQUIRED)


def require_runner(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    """仅允许 Runner 执行令牌访问控制面接口，用户 JWT 不得冒充 Runner。"""
    if auth.kind == "runner":
        assert_production_runner_scoped(auth)
        return auth
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=msg.AUTH_RUNNER_TOKEN_REQUIRED,
    )


def require_ops_admin(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    """运维配置写权限。当前等同 platform admin；见 ``is_ops_admin`` 扩展点。"""
    if is_ops_admin(auth):
        return auth
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg.AUTH_ADMIN_REQUIRED)


def assert_can_manage_users(auth: AuthContext, db: Session | None = None) -> None:
    """平台 admin，或当前组织（X-Org-Id）的 owner/admin。"""
    if is_platform_admin(auth):
        return
    oid = (auth.org_id or "").strip()
    if not oid or db is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=msg.AUTH_ORG_CONTEXT_REQUIRED
        )
    from .tenancy.organizations import assert_can_manage_org  # 延迟：organizations 顶栏 import projects

    try:
        assert_can_manage_org(db, auth, oid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def require_user_manager(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """用户管理 / 组织范围审计：平台 admin 或组织 owner/admin。"""
    assert_can_manage_users(auth, db)
    return auth


def assert_operator_role_ok(auth: AuthContext, role: str) -> None:
    """operator 不能创建/指定 admin 角色。"""
    if is_platform_admin(auth):
        return
    if (role or "").strip() == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=msg.AUTH_OPERATOR_NO_ADMIN,
        )


def assert_create_duty_ok(auth: AuthContext, duty: str) -> None:
    """非系统管理员不能创建系统管理员。"""
    if is_platform_admin(auth):
        return
    if (duty or "").strip() == "sys_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=msg.AUTH_OPERATOR_NO_ADMIN,
        )


def assert_runner_id_allowed(auth: AuthContext, runner_id: str) -> None:
    """Runner Token 只能操作自身 runner_id；全局执行 Token 不限制具体节点。"""
    if auth.kind != "runner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=msg.AUTH_RUNNER_TOKEN_REQUIRED,
        )
    if not auth.runner_id:
        return
    if (runner_id or "").strip() != auth.runner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=msg.AUTH_RUNNER_IMPERSONATE,
        )


def assert_production_runner_scoped(auth: AuthContext) -> None:
    """生产环境禁止全局、无 runner/scope 绑定的执行令牌。"""
    if is_production() and auth.kind == "runner" and not auth.runner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="生产环境拒绝无 scope 的全局 Runner Token；请签发独立 Runner Token",
        )


def runner_scope_allows_project(
    db: Session,
    *,
    org_id: str = "",
    project_ids: tuple[str, ...] | list[str] = (),
    job_project_id: str = "",
) -> bool:
    """Runner 作用域是否允许领取/操作某 Job 的 project_id。

    - org_id 与 project_ids 皆空：不限制（兼容旧 Runner）
    - 仅 project_ids：job.project_id 必须在列表中（空 project 的 Job 拒绝）
    - 仅 org_id：Job 所属项目的 org_id 须匹配（无 project 的 Job 拒绝）
    - 二者皆有：须同时满足
    """
    oid = (org_id or "").strip()
    allowed = tuple(str(p).strip() for p in (project_ids or ()) if str(p).strip())
    if not oid and not allowed:
        return True
    pid = (job_project_id or "").strip()
    if not pid:
        return False
    if allowed and pid not in allowed:
        return False
    if oid:
        proj = db_get(db, ProjectRow, pid)
        if proj is None:
            return False
        if (getattr(proj, "org_id", None) or "").strip() != oid:
            return False
    return True


def assert_runner_scope_for_job(db: Session, auth: AuthContext, job_project_id: str) -> None:
    """独立 Runner Token 越权项目时 403；全局执行 Token / 用户跳过。"""
    if auth.kind != "runner" or not auth.runner_id:
        return
    if runner_scope_allows_project(
        db,
        org_id=auth.org_id,
        project_ids=auth.project_ids,
        job_project_id=job_project_id,
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=msg.AUTH_RUNNER_SCOPE_DENIED,
    )


# 兼容旧名
require_token = require_auth
