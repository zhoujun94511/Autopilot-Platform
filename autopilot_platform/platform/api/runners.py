"""Runner register / heartbeat / tokens / managed local process."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    HeartbeatIn,
    ManagedRunnerLogsOut,
    ManagedRunnerStartIn,
    ManagedRunnerStatusOut,
    RunnerListPage,
    RunnerDeviceInventoryOut,
    RunnerDeviceSelectionIn,
    RunnerDeviceSelectionOut,
    RunnerOut,
    RunnerProvisionIn,
    RunnerProvisionOut,
    RunnerRegister,
    RunnerScopePatch,
    RunnerTokenIssue,
    RunnerTokenOut,
)

from ..auth import (
    AuthContext,
    assert_production_runner_scoped,
    assert_runner_id_allowed,
    require_admin,
    require_auth,
    require_ops_admin,
    require_runner,
)
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.models import ProjectRow, RunnerRow, db_get
from ..core.settings import allow_managed_runner, managed_runner_deny_message
from ..tenancy.organizations import org_member_role
from ..tenancy.projects import is_platform_admin
from ..ops import audit as audit_svc
from ..services.execution import runners as services
from ..services.execution.runners.managed import get_managed_runner_manager, probe_local_devices
from ..services.remote.policy import can_user_manage_runner

router = APIRouter(tags=["runners"])


@router.post("/runners/register", response_model=RunnerOut)
def api_register(
    body: RunnerRegister,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerOut:

    existing = db_get(db, RunnerRow, body.runner_id)
    if auth.kind == "user":
        if (body.registration_source or "").strip().lower() != "ide":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户会话只能预注册 IDE Runner",
            )
        if existing is not None:
            source = (existing.registration_source or "platform").strip().lower()
            owner = (existing.owner_user_id or "").strip()
            if source != "ide" or (
                owner and owner != auth.user_id and not is_platform_admin(auth)
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="该 Runner 已由其他来源或用户登记",
                )
        return services.register_runner(
            db,
            body,
            owner_user_id=auth.user_id,
            registration_source="ide",
        )

    assert_production_runner_scoped(auth)
    assert_runner_id_allowed(auth, body.runner_id)
    # Runner 凭据不能把新节点伪装成 IDE 私有资源；已有 managed/ide 来源保持不变。
    source = (
        (existing.registration_source or "platform")
        if existing is not None
        else "platform"
    )
    return services.register_runner(db, body, registration_source=source)


@router.post("/runners/heartbeat", response_model=RunnerOut)
def api_heartbeat(
    body: HeartbeatIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> RunnerOut:
    assert_runner_id_allowed(auth, body.runner_id)
    try:
        return services.heartbeat(db, body)
    except LookupError as exc:
        # 理论上 heartbeat 已自愈注册；保留 404 兼容旧行为
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runners", response_model=RunnerListPage)
def api_list_runners(
    project_id: str = Query(""),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = services.list_runners(
            db, auth=auth, project_id=project_id, page=pg, page_size=size
        )
        return RunnerListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/runners/managed", response_model=ManagedRunnerStatusOut)
def api_managed_runner_status(
    log_lines: int = Query(40, ge=0, le=500),
    _auth: AuthContext = Depends(require_ops_admin),
) -> ManagedRunnerStatusOut:
    """本机托管 Runner 状态（PID / 日志尾 / CLI 降级命令）。仅 ops_admin。"""
    return get_managed_runner_manager().status(log_lines=log_lines)


@router.get("/runners/managed/logs", response_model=ManagedRunnerLogsOut)
def api_managed_runner_logs(
    lines: int = Query(100, ge=1, le=500),
    _auth: AuthContext = Depends(require_ops_admin),
) -> ManagedRunnerLogsOut:
    """本机托管 Runner 日志尾部。仅 ops_admin。"""
    return get_managed_runner_manager().logs(lines=lines)


@router.post(
    "/runners/managed/device-probe", response_model=RunnerDeviceInventoryOut
)
def api_managed_runner_device_probe(
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_ops_admin),
) -> RunnerDeviceInventoryOut:
    """扫描 Platform 同机 Android/iOS 设备；仅 loopback 托管能力开放时可用。"""
    if not allow_managed_runner():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=managed_runner_deny_message(),
        )
    return probe_local_devices(db)


@router.post("/runners/managed/start", response_model=ManagedRunnerStatusOut)
def api_managed_runner_start(
    body: ManagedRunnerStartIn | None = None,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_ops_admin),
) -> ManagedRunnerStatusOut:
    """启动本机托管 Runner（subprocess）。仅 ops_admin；受 MC_ALLOW_MANAGED_RUNNER 控制。"""
    payload = body or ManagedRunnerStartIn()
    mgr = get_managed_runner_manager()
    try:
        out = mgr.start(
            db,
            org_id=payload.org_id,
            project_ids=payload.project_ids,
            poll_interval=payload.poll_interval,
        )
        audit_svc.write_audit_auth(
            db,
            auth,
            action="runner.managed_start",
            resource_type="runner",
            resource_id=out.runner_id,
            detail=f"pid={out.pid}",
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/runners/managed/stop", response_model=ManagedRunnerStatusOut)
def api_managed_runner_stop(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_ops_admin),
) -> ManagedRunnerStatusOut:
    """停止本机托管 Runner。仅 ops_admin。"""
    mgr = get_managed_runner_manager()
    try:
        out = mgr.stop()
        audit_svc.write_audit_auth(
            db,
            auth,
            action="runner.managed_stop",
            resource_type="runner",
            resource_id=out.runner_id,
            detail=f"exit_code={out.exit_code}",
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/runners/provision", response_model=RunnerProvisionOut)
def api_provision_runner(
    body: RunnerProvisionIn,
    request: Request,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerProvisionOut:
    """预配远程节点并一次性返回 scoped Token 与启动命令。"""
    oid = (body.org_id or auth.org_id or "").strip()
    if not is_platform_admin(auth):
        if not oid or org_member_role(db, auth.user_id, oid) not in {"owner", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="仅平台管理员或组织 owner/admin 可创建远程节点",
            )
    for project_id in body.project_ids:
        project = db_get(db, ProjectRow, project_id)
        if project is None:
            raise HTTPException(status_code=400, detail=f"项目不存在：{project_id}")
        project_org = (project.org_id or "").strip()
        if oid and project_org and project_org != oid:
            raise HTTPException(
                status_code=400,
                detail=f"项目 {project_id} 不属于组织 {oid}",
            )
    row = db_get(db, RunnerRow, body.runner_id)
    if row is None:
        row = RunnerRow(
            runner_id=body.runner_id,
            hostname="",
            version="",
            org_id=oid,
            registration_source="platform",
        )
        row.project_ids = list(body.project_ids)
        db.add(row)
        db.commit()
    elif (row.org_id or "").strip() not in {"", oid} and not is_platform_admin(auth):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runner ID 已属于其他组织",
        )
    rid, raw, out_oid, pids = services.issue_runner_token(
        db,
        body.runner_id,
        org_id=oid,
        project_ids=body.project_ids,
    )
    server = str(request.base_url).rstrip("/")
    command = (
        "python -m autopilot_platform.runner "
        f"--server {server} --token-env MC_RUNNER_TOKEN --runner-id {rid}"
    )
    return RunnerProvisionOut(
        runner_id=rid,
        api_token=raw,
        org_id=out_oid,
        project_ids=pids,
        command=command,
    )


@router.get(
    "/runners/{runner_id}/device-inventory",
    response_model=RunnerDeviceInventoryOut,
)
def api_runner_device_inventory(
    runner_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerDeviceInventoryOut:
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"runner not found: {runner_id}")
    runner_self = (
        auth.kind == "runner"
        and (getattr(auth, "runner_id", None) or "").strip() == runner_id
    )
    if not runner_self and not can_user_manage_runner(db, auth, row):
        raise HTTPException(status_code=403, detail="无权管理该 Runner 的设备")
    return services.get_device_inventory(db, runner_id)


@router.patch(
    "/runners/{runner_id}/device-selection",
    response_model=RunnerDeviceSelectionOut,
)
def api_runner_device_selection(
    runner_id: str,
    body: RunnerDeviceSelectionIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerDeviceSelectionOut:
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"runner not found: {runner_id}")
    if not can_user_manage_runner(db, auth, row):
        raise HTTPException(status_code=403, detail="无权修改该 Runner 的设备")
    try:
        return services.update_device_selection(
            db, runner_id, action=body.action, udids=body.udids
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/runners/{runner_id}")
def api_deregister_runner(
    runner_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """注销 Runner（admin 运维）：删除节点记录及其设备行。

    - 存在占用中设备时拒绝（先释放占用 / 等任务结束）。
    - 在线节点也可注销，但若该机 Runner 仍在运行，下次心跳会自愈重建。
    - 远程节点无法由 Platform 直接杀进程；仅注销登记。本机托管请用
      ``POST /runners/managed/stop``。
    """
    try:
        row = db_get(db, RunnerRow, runner_id)
        if row is None:
            raise LookupError(f"runner not found: {runner_id}")
        if not can_user_manage_runner(db, auth, row):
            raise PermissionError("无权管理该 Runner")
        out = services.deregister_runner(db, runner_id)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="runner.deregister",
            resource_type="runner",
            resource_id=runner_id,
            detail=f"devices_removed={out.get('devices_removed')}",
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/runners/{runner_id}/token", response_model=RunnerTokenOut)
def api_issue_runner_token(
    runner_id: str,
    body: RunnerTokenIssue | None = None,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> RunnerTokenOut:
    """签发/轮换独立 Runner Token；body 可绑 org_id / project_ids 作用域。"""
    payload = body or RunnerTokenIssue()
    try:
        rid, raw, oid, pids = services.issue_runner_token(
            db,
            runner_id,
            org_id=payload.org_id,
            project_ids=payload.project_ids,
        )
        audit_svc.write_audit_auth(
            db,
            auth,
            action="runner.token_issue",
            resource_type="runner",
            resource_id=rid,
            detail=f"org_id={oid} projects={len(pids)}",
        )
        return RunnerTokenOut(
            runner_id=rid, api_token=raw, org_id=oid, project_ids=pids
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/runners/{runner_id}/scoped-token", response_model=RunnerTokenOut)
def api_issue_user_scoped_runner_token(
    runner_id: str,
    body: RunnerTokenIssue,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> RunnerTokenOut:
    """平台管理员为 IDE Runner 签发 scoped Token（cap.ide.runner.start_scoped）。"""
    from ..tenancy.projects import assert_can_write_project  # 延迟：仅签发 scoped token

    if auth.kind != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="必须使用已登录用户会话签发 scoped Runner Token",
        )
    if not is_platform_admin(auth):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅平台管理员可签发 scoped Runner Token；Operator 请使用管理员预配的 Token",
        )
    pids = list(dict.fromkeys(str(x).strip() for x in (body.project_ids or []) if str(x).strip()))
    oid = (body.org_id or auth.org_id or "").strip()
    if not pids and not oid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scoped Runner Token 须绑定 org_id 或至少一个 project_id",
        )
    try:
        for pid in pids:
            assert_can_write_project(db, auth, pid)
            project = db_get(db, ProjectRow, pid)
            project_org = str(getattr(project, "org_id", "") or "").strip()
            if oid and project_org and oid != project_org:
                raise PermissionError(f"项目 {pid} 不属于组织 {oid}")
        if oid:
            # 延迟：仅签发带 org_id 的 scoped token 时校验组织
            from ..tenancy.organizations import assert_can_access_org

            assert_can_access_org(db, auth, oid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"runner not found: {runner_id}",
        )
    if (row.registration_source or "platform").strip().lower() != "ide":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户 scoped Runner Token 仅可签发给已预注册的 IDE Runner",
        )
    owner = str(getattr(row, "owner_user_id", "") or "").strip()
    if not is_platform_admin(auth):
        if owner and owner != auth.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该 Runner 已由其他用户绑定",
            )
        row.owner_user_id = auth.user_id
    rid, raw, out_oid, out_pids = services.issue_runner_token(
        db,
        runner_id,
        org_id=oid,
        project_ids=pids,
    )
    audit_svc.write_audit_auth(
        db,
        auth,
        action="runner.scoped_token_issue",
        resource_type="runner",
        resource_id=rid,
        detail=f"org_id={out_oid} projects={len(out_pids)}",
    )
    return RunnerTokenOut(
        runner_id=rid,
        api_token=raw,
        org_id=out_oid,
        project_ids=out_pids,
    )


@router.patch("/runners/{runner_id}/scope", response_model=RunnerOut)
def api_patch_runner_scope(
    runner_id: str,
    body: RunnerScopePatch,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> RunnerOut:
    """更新 Runner 作用域（不轮换 token）。空 org_id / 空 project_ids = 解除限制。"""
    try:
        out = services.set_runner_scope(
            db,
            runner_id,
            org_id=body.org_id,
            project_ids=body.project_ids,
        )
        audit_svc.write_audit_auth(
            db,
            auth,
            action="runner.scope_patch",
            resource_type="runner",
            resource_id=runner_id,
            detail=f"org_id={out.org_id} projects={len(out.project_ids)}",
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
