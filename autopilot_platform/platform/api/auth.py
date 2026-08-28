"""Auth: login / OIDC / SAML / me (public) + user admin (authenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    IdeHandoffConsumeIn,
    IdeHandoffOut,
    LoginIn,
    LogoutIn,
    RefreshIn,
    TokenOut,
    UserCreate,
    UserListPage,
    UserOut,
    UserUpdate,
)

from ..auth import AuthContext, require_admin, require_auth, require_user_manager
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.models import UserRow, db_get
from ..core import api_messages as msg
from ..core.login_rate import assert_login_allowed, note_login_failure, note_login_success
from ..identity.refresh_cookie import (
    clear_refresh_cookie,
    resolve_refresh_token,
    set_refresh_cookie,
)
from ..ops import audit as audit_svc
from ..identity import oidc as oidc_svc
from ..identity import saml as saml_svc
from ..artifacts import users_artifacts as ua
from ..identity import session_tokens as session_svc

public_router = APIRouter(tags=["auth"])
router = APIRouter(tags=["auth"])

@public_router.post("/auth/login", response_model=TokenOut)
def api_login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> TokenOut:
    client_host = (request.client.host if request.client else "") or "unknown"
    rate_key = f"{client_host}|{(body.username or '').strip().lower()}"
    try:
        assert_login_allowed(rate_key, db)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    try:
        out = ua.login(db, body)
        note_login_success(rate_key, db)
        audit_svc.write_audit(
            db,
            action="auth.login",
            actor=out.user.username,
            actor_kind="user",
            detail="password",
        )
        # AUD-2026-02-C：浏览器 HttpOnly Cookie；JSON 仍含 refresh 供 IDE
        if out.refresh_token:
            set_refresh_cookie(response, out.refresh_token, request)
        return out
    except PermissionError as exc:
        note_login_failure(rate_key, db)
        ua_hdr = (request.headers.get("user-agent") or "").strip()[:160]
        detail = f"ip={client_host}"
        if ua_hdr:
            detail = f"{detail} ua={ua_hdr}"
        audit_svc.write_audit(
            db,
            action="auth.login_failed",
            actor=(body.username or "").strip()[:128],
            actor_kind="user",
            detail=detail,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@public_router.post("/auth/refresh", response_model=TokenOut)
def api_refresh(
    request: Request,
    response: Response,
    body: RefreshIn | None = None,
    db: Session = Depends(get_session),
) -> TokenOut:
    raw = resolve_refresh_token(
        request, body.refresh_token if body is not None else ""
    )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=msg.AUTH_REFRESH_INVALID
        )
    try:
        out = session_svc.refresh_session(db, raw)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if out.refresh_token:
        set_refresh_cookie(response, out.refresh_token, request)
    return out


@public_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def api_logout(
    request: Request,
    response: Response,
    body: LogoutIn | None = None,
    db: Session = Depends(get_session),
) -> None:
    raw = resolve_refresh_token(
        request, body.refresh_token if body is not None else ""
    )
    if raw:
        session_svc.revoke_refresh_token(db, raw)
    clear_refresh_cookie(response, request)


@public_router.get("/auth/oidc/status")
def api_oidc_status() -> dict:
    return oidc_svc.oidc_status()


@public_router.get("/auth/oidc/start")
def api_oidc_start() -> RedirectResponse:
    try:
        url, _state = oidc_svc.build_authorize_url()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@public_router.get("/auth/oidc/callback")
def api_oidc_callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    error_description: str = Query(""),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    if error:
        detail = (error_description or "").strip() or msg.AUTH_SSO_FAILED
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_OIDC_CODE_STATE_REQUIRED)
    try:
        token = oidc_svc.complete_oidc_login(db, code=code, state=state)
        audit_svc.write_audit(
            db,
            action="auth.oidc_login",
            actor=token.user.username,
            actor_kind="user",
            detail="oidc",
        )
        dest = oidc_svc.frontend_success_redirect(token)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=msg.AUTH_SSO_FAILED
        ) from exc
    return RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)


@public_router.get("/auth/saml/status")
def api_saml_status() -> dict:
    return saml_svc.saml_status()


@public_router.get("/auth/saml/metadata")
def api_saml_metadata() -> Response:
    try:
        xml = saml_svc.sp_metadata_xml()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return Response(content=xml, media_type="application/samlmetadata+xml")


@public_router.get("/auth/saml/login")
def api_saml_login() -> RedirectResponse:
    try:
        url = saml_svc.build_login_redirect_url()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@public_router.post("/auth/saml/acs")
async def api_saml_acs(
    request: Request,
    db: Session = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    saml_response = str(form.get("SAMLResponse") or "")
    if not saml_response:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_SAML_RESPONSE_REQUIRED)
    try:
        token = saml_svc.complete_saml_login(db, saml_response_b64=saml_response)
        audit_svc.write_audit(
            db,
            action="auth.saml_login",
            actor=token.user.username,
            actor_kind="user",
            detail="saml",
        )
        dest = saml_svc.frontend_success_redirect(token)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=msg.AUTH_SSO_FAILED
        ) from exc
    return RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)


@router.post("/auth/ide-handoff", response_model=IdeHandoffOut)
def api_create_ide_handoff(
    auth: AuthContext = Depends(require_auth),
) -> IdeHandoffOut:
    """IDE 打开浏览器前换一次性短码，避免把 JWT 写进地址栏。"""
    if auth.kind != "user":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_NOT_USER_SESSION
        )
    from ..identity import ide_handoff as handoff_svc  # 延迟：仅 IDE 交接端点

    code, ttl = handoff_svc.issue(auth.user_id)
    return IdeHandoffOut(code=code, expires_in=ttl)


@public_router.post("/auth/ide-handoff/consume", response_model=TokenOut)
def api_consume_ide_handoff(
    body: IdeHandoffConsumeIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> TokenOut:
    from ..identity import ide_handoff as handoff_svc  # 延迟：仅 IDE 交接端点

    uid = handoff_svc.consume(body.code)
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=msg.AUTH_HANDOFF_INVALID
        )
    row = db_get(db, UserRow, uid)
    if row is None or row.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=msg.AUTH_HANDOFF_INVALID
        )
    try:
        out = session_svc.issue_session(db, row)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if out.refresh_token:
        set_refresh_cookie(response, out.refresh_token, request)
    audit_svc.write_audit(
        db,
        action="auth.ide_handoff",
        actor=out.user.username,
        actor_kind="user",
        detail="ide",
    )
    return out


@public_router.get("/auth/me", response_model=UserOut)
def api_me(auth: AuthContext = Depends(require_auth), db: Session = Depends(get_session)) -> UserOut:
    if auth.kind != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_NOT_USER_SESSION)

    row = db_get(db, UserRow, auth.user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.AUTH_USER_NOT_FOUND)
    return ua.user_to_out(row)


@router.post("/auth/users", response_model=UserOut)
def api_create_user(
    body: UserCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_user_manager),
) -> UserOut:
    from ..auth import assert_create_duty_ok  # 延迟：auth 包内避免循环

    assert_create_duty_ok(auth, body.duty)
    try:
        out = ua.create_user(db, body, auth)
        bits = [out.username, f"duty={body.duty}"]
        if body.project_id:
            bits.append(f"project={body.project_id}")
        audit_svc.write_audit_auth(
            db,
            auth,
            action="user.create",
            resource_type="user",
            resource_id=out.id,
            detail=" ".join(bits),
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        code = (
            status.HTTP_403_FORBIDDEN
            if isinstance(exc, PermissionError)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/auth/users", response_model=UserListPage)
def api_list_users(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_user_manager),
) -> UserListPage:

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = ua.list_users(db, auth, page=pg, page_size=size)
    return UserListPage(items=items, total=total, page=pg, page_size=size)


@router.patch("/auth/users/{user_id}", response_model=UserOut)
def api_update_user(
    user_id: str,
    body: UserUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_user_manager),
) -> UserOut:
    try:
        out = ua.update_user(db, user_id, body, auth)
        audit_svc.write_audit_auth(
            db, auth, action="user.update", resource_type="user", resource_id=user_id
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/auth/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_delete_user(
    user_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> None:
    try:
        ua.delete_user(db, user_id, auth)
        audit_svc.write_audit_auth(
            db, auth, action="user.delete", resource_type="user", resource_id=user_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


