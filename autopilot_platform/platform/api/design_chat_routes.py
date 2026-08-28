"""设计域 Chat / 实验动作 API。"""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..ops import audit as audit_svc
from ..design.design_schemas import (
    ChatMessageIn,
    ChatSessionCreate,
    ChatSessionListPage,
    ChatSessionOut,
    ChatSessionUpdate,
    ChatMessageOut,
)
from ..services.design import access as design_access
from ..services.design.chat import sessions as chat_sessions
from ..services.design.chat import prompts as chat_prompts
from ..services.design.chat import messages as chat_messages
from ..services.design.chat import streaming as chat_streaming
from ..services.design.chat import export as chat_export
from ..services.design.chat import suggestions as chat_suggestions
from ..services.design import experimental_actions as exp_svc

router = APIRouter(tags=["design"])


# ── Chat ────────────────────────────────────────────────────────────


@router.get("/design/chat/options")
def api_chat_options(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """只读：当前 provider/model/temperature 与建议模型列表（密钥不另存）。"""
    _ = db
    design_access.require_design_user(auth)
    return chat_prompts.chat_options()


@router.get("/design/chat/templates")
def api_chat_templates(
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    _ = db
    design_access.require_design_user(auth)
    return chat_prompts.chat_templates()


@router.get("/design/chat/suggestions")
def api_chat_suggestions(
    context: str | None = Query(default=None),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    _ = db
    design_access.require_design_user(auth)
    return {
        "success": True,
        "suggestions": chat_suggestions.starter_suggestions(context=context or ""),
    }


@router.get("/design/chat/sessions", response_model=ChatSessionListPage)
def api_list_chat_sessions(
    project_id: str | None = Query(default=None),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ChatSessionListPage:

    design_access.require_design_user(auth)
    scope = design_access.resolve_list_scope(db, auth, project_id)
    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = chat_sessions.list_sessions(
        db,
        project_ids=scope,
        created_by=auth.username or auth.user_id,
        page=pg,
        page_size=size,
    )
    return ChatSessionListPage(items=items, total=total, page=pg, page_size=size)


@router.post("/design/chat/sessions", response_model=ChatSessionOut)
def api_create_chat_session(
    body: ChatSessionCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ChatSessionOut:
    design_access.require_design_user(auth)
    if body.project_id:
        design_access.ensure_project_write(db, auth, body.project_id)
    return chat_sessions.create_session(db, body, auth)


def _chat_session_or_http(
    db: Session, session_id: str, auth: AuthContext,
):
    """加载会话并校验归属；404 / 403 映射。"""
    try:
        return chat_sessions.load_session_for_user(db, session_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/design/chat/sessions/{session_id}", response_model=ChatSessionOut)
def api_rename_chat_session(
    session_id: str,
    body: ChatSessionUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ChatSessionOut:
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_write(db, auth, session.project_id)
    try:
        return chat_sessions.rename_session(db, session_id, body, auth)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/design/chat/sessions/{session_id}/clear")
def api_clear_chat_session(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_write(db, auth, session.project_id)
    return chat_messages.clear_session_messages(db, session_id, auth)


@router.get("/design/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def api_list_chat_messages(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[ChatMessageOut]:
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_access(db, auth, session.project_id)
    return chat_messages.list_messages(db, session_id)


@router.delete("/design/chat/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_chat_session(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_write(db, auth, session.project_id)
    chat_sessions.delete_session(db, session_id, auth)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/design/chat/message")
def api_chat_message(
    body: ChatMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, body.session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_write(db, auth, session.project_id)

    # 实验动作：mode=action 时强制识别；或全局开关开启时自动识别
    mode = str(getattr(body, "mode", "") or "").strip().lower()
    want_action = mode == "action" or bool(getattr(body, "require_confirmation", False))
    if want_action or exp_svc.experimental_actions_enabled():
        proposal = exp_svc.propose_from_query(
            body.message,
            project_id=session.project_id or "",
            session_id=body.session_id,
            force=want_action,
            created_by=(auth.username or auth.user_id or "").strip(),
        )
        if proposal and proposal.get("status") == "needs_confirmation":
            return proposal

    try:
        return chat_messages.send_message(db, body, auth)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/design/experimental-actions/confirm")
def api_experimental_confirm(
    body: dict,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    design_access.require_design_user(auth)

    eid = str((body or {}).get("execution_id") or "").strip()
    if not eid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要 execution_id")
    meta = (body or {}).get("metadata") if isinstance((body or {}).get("metadata"), dict) else {}
    out = exp_svc.confirm_action(db, auth, execution_id=eid, metadata=meta)
    if out.get("success"):
        audit_svc.write_audit_auth(
            db,
            auth,
            action="design.experimental_action.confirm",
            detail=str((out.get("plan") or {}).get("tool_name") or ""),
        )
    if out.get("error") == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=out.get("message") or "无权确认该动作",
        )
    if not out.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=out.get("message") or "确认失败",
        )
    return out


@router.post("/design/experimental-actions/cancel")
def api_experimental_cancel(
    body: dict,
    _db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """取消实验动作（内存态）；保留 _db 依赖以维持与其它设计域写接口一致的 session 生命周期。"""
    _ = _db
    design_access.require_design_user(auth)

    eid = str((body or {}).get("execution_id") or "").strip()
    if not eid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要 execution_id")
    out = exp_svc.cancel_action(
        eid, reason=str((body or {}).get("reason") or ""), auth=auth
    )
    if out.get("error") == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=out.get("message") or "无权取消该动作",
        )
    return out


@router.post("/design/chat/stream")
def api_chat_stream(
    body: ChatMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, body.session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_write(db, auth, session.project_id)

    # 流式路径：若命中实验动作，以单条 SSE event 返回确认请求
    mode = str(getattr(body, "mode", "") or "").strip().lower()
    want_action = mode == "action" or bool(getattr(body, "require_confirmation", False))
    if want_action or exp_svc.experimental_actions_enabled():
        proposal = exp_svc.propose_from_query(
            body.message,
            project_id=session.project_id or "",
            session_id=body.session_id,
            force=want_action,
            created_by=(auth.username or auth.user_id or "").strip(),
        )
        if proposal and proposal.get("status") == "needs_confirmation":

            def _action_sse():
                yield f"event: action\ndata: {json.dumps(proposal, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {}\n\n"

            return StreamingResponse(_action_sse(), media_type="text/event-stream")

    def _gen():
        yield from chat_streaming.iter_sse_chunks(db, body, auth)

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/design/chat/sessions/{session_id}/export")
def api_export_chat_session(
    session_id: str,
    fmt: str = Query(default="json", alias="format"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    design_access.require_design_user(auth)
    session = _chat_session_or_http(db, session_id, auth)
    if session.project_id:
        design_access.ensure_row_project_access(db, auth, session.project_id)
    try:
        raw, media, filename = chat_export.export_session(db, session_id, fmt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return StreamingResponse(
        iter([raw]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
