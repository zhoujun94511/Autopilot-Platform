"""Device remote sessions (Platform Web 远控)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    DeviceLogLinesIn,
    DeviceRemoteCommandOut,
    DeviceRemoteCommandIn,
    DeviceRemoteCommandStatusOut,
    DeviceRemoteParticipantJoinIn,
    DeviceRemoteParticipantOut,
    DeviceRemotePrewarmHintOut,
    DeviceRemoteRunnerStatusIn,
    DeviceRemoteSessionCreate,
    DeviceRemoteSessionOut,
    MediaMessageIn,
    MediaPollOut,
    SignalingMessageIn,
    SignalingPollOut,
)

from ..auth import AuthContext, require_auth, require_runner, require_stream_auth
from ..core.db import get_session, session_factory
from ..ops import audit as audit_svc
from ..services.remote import sessions as remote_svc
from ..services.remote import device_log_bus

router = APIRouter(tags=["device-remote"])


def _http_from_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post(
    "/devices/{device_id}/remote-sessions",
    response_model=DeviceRemoteSessionOut,
)
def api_create_remote_session(
    device_id: str,
    body: DeviceRemoteSessionCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteSessionOut:
    try:
        out = remote_svc.create_remote_session(db, device_id, body, auth)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="device.remote_session_start",
        resource_type="device_remote_session",
        resource_id=out.id,
        detail=f"device_id={out.device_id};udid={out.udid};platform={out.platform}",
    )
    return out


@router.post(
    "/devices/{device_id}/remote-sessions/join",
    response_model=DeviceRemoteSessionOut,
)
def api_join_device_remote_session(
    device_id: str,
    body: DeviceRemoteParticipantJoinIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteSessionOut:
    try:
        return remote_svc.join_device_remote_session(db, device_id, body, auth)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post(
    "/device-remote-sessions/{session_id}/participants",
    response_model=DeviceRemoteSessionOut,
)
def api_join_remote_session(
    session_id: str,
    body: DeviceRemoteParticipantJoinIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteSessionOut:
    try:
        return remote_svc.join_remote_session(db, session_id, body, auth)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.get(
    "/device-remote-sessions/{session_id}/participants",
    response_model=list[DeviceRemoteParticipantOut],
)
def api_list_remote_participants(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[DeviceRemoteParticipantOut]:
    try:
        return remote_svc.list_remote_participants(db, session_id, auth)
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.delete(
    "/device-remote-sessions/{session_id}/participants/{participant_id}",
    response_model=DeviceRemoteParticipantOut,
)
def api_leave_remote_participant(
    session_id: str,
    participant_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteParticipantOut:
    try:
        return remote_svc.leave_remote_participant(
            db, session_id, participant_id, auth
        )
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.post(
    "/device-remote-sessions/{session_id}/participants/{participant_id}/promote",
    response_model=DeviceRemoteParticipantOut,
)
def api_promote_remote_participant(
    session_id: str,
    participant_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteParticipantOut:
    try:
        out = remote_svc.promote_remote_participant(
            db, session_id, participant_id, auth
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="device.remote_participant_promote",
        resource_type="device_remote_session",
        resource_id=session_id,
        detail=f"participant_id={participant_id};user_id={out.user_id}",
    )
    return out


@router.get(
    "/device-remote-sessions/{session_id}",
    response_model=DeviceRemoteSessionOut,
)
def api_get_remote_session(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteSessionOut:
    try:
        return remote_svc.get_remote_session(db, session_id, auth)
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.delete(
    "/device-remote-sessions/{session_id}",
    response_model=DeviceRemoteSessionOut,
)
def api_close_remote_session(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteSessionOut:
    try:
        out = remote_svc.close_remote_session(db, session_id, auth)
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="device.remote_session_stop",
        resource_type="device_remote_session",
        resource_id=out.id,
        detail=f"device_id={out.device_id};status={out.status}",
    )
    return out


@router.post("/device-remote-sessions/{session_id}/offer")
def api_post_offer(
    session_id: str,
    body: SignalingMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, str]:
    if not (body.type or "").strip():
        body = body.model_copy(update={"type": "offer"})
    try:
        return remote_svc.post_signaling(db, session_id, auth, body)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/answer")
def api_post_answer(
    session_id: str,
    body: SignalingMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, str]:
    if not (body.type or "").strip():
        body = body.model_copy(update={"type": "answer"})
    try:
        return remote_svc.post_signaling(db, session_id, auth, body)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/ice")
def api_post_ice(
    session_id: str,
    body: SignalingMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, str]:
    if not (body.type or "").strip():
        body = body.model_copy(update={"type": "ice"})
    try:
        return remote_svc.post_signaling(db, session_id, auth, body)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.get(
    "/device-remote-sessions/{session_id}/signaling-poll",
    response_model=SignalingPollOut,
)
def api_poll_signaling(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> SignalingPollOut:
    try:
        return remote_svc.poll_signaling(db, session_id, auth)
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/media")
def api_post_media(
    session_id: str,
    body: MediaMessageIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, str]:
    try:
        return remote_svc.post_media(db, session_id, auth, body)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post(
    "/device-remote-sessions/{session_id}/commands",
    response_model=DeviceRemoteCommandStatusOut,
)
def api_post_remote_command(
    session_id: str,
    body: DeviceRemoteCommandIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteCommandStatusOut:
    try:
        out = remote_svc.post_command(db, session_id, auth, body)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action=f"device.remote_command.{body.name}",
        resource_type="device_remote_session",
        resource_id=session_id,
        detail=f"request_id={out.request_id}",
    )
    return out


@router.get(
    "/device-remote-sessions/{session_id}/commands/{request_id}",
    response_model=DeviceRemoteCommandStatusOut,
)
def api_get_remote_command(
    session_id: str,
    request_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceRemoteCommandStatusOut:
    try:
        return remote_svc.get_command_status(
            db, session_id, request_id, auth
        )
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.get(
    "/device-remote-sessions/{session_id}/media-poll",
    response_model=MediaPollOut,
)
def api_poll_media(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> MediaPollOut:
    try:
        return remote_svc.poll_media(db, session_id, auth)
    except (LookupError, PermissionError) as exc:
        raise _http_from_exc(exc) from exc


@router.get(
    "/runners/me/remote-commands",
    response_model=list[DeviceRemoteCommandOut],
)
def api_runner_remote_commands(
    runner_id: str = "",
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> list[DeviceRemoteCommandOut]:
    try:
        return remote_svc.list_runner_commands(db, auth, runner_id=runner_id)
    except PermissionError as exc:
        raise _http_from_exc(exc) from exc


@router.get(
    "/runners/me/remote-prewarm-hints",
    response_model=list[DeviceRemotePrewarmHintOut],
)
def api_runner_remote_prewarm_hints(
    runner_id: str = "",
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> list[DeviceRemotePrewarmHintOut]:
    try:
        return remote_svc.list_prewarm_hints(db, auth, runner_id=runner_id)
    except PermissionError as exc:
        raise _http_from_exc(exc) from exc


@router.post(
    "/device-remote-sessions/{session_id}/runner-status",
    response_model=DeviceRemoteSessionOut,
)
def api_runner_session_status(
    session_id: str,
    body: DeviceRemoteRunnerStatusIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> DeviceRemoteSessionOut:
    try:
        return remote_svc.update_runner_status(
            db,
            session_id,
            auth,
            status=body.status,
            error_message=body.error_message,
            capabilities=body.capabilities or None,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/logs/stream-token")
def api_create_device_log_stream_token(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    try:
        return remote_svc.issue_device_log_stream_token(db, session_id, auth)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/logs")
def api_ingest_device_logs(
    session_id: str,
    body: DeviceLogLinesIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> dict[str, int]:
    try:
        return remote_svc.ingest_device_logs(
            db, session_id, auth, list(body.lines or [])
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc


@router.post("/device-remote-sessions/{session_id}/logs/clear")
def api_clear_device_logs(
    session_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, str]:
    try:
        remote_svc.request_device_log_control(
            db, session_id, auth, name="log.clear"
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http_from_exc(exc) from exc
    return {"status": "accepted"}


@router.get("/device-remote-sessions/{session_id}/logs/stream")
async def api_stream_device_logs(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(require_stream_auth),
    level: str = Query("I", max_length=8),
    tag: str = Query("", max_length=64),
) -> StreamingResponse:
    """设备日志 SSE。鉴权用短时票；火管数据不走 WebRTC / media-poll。"""
    factory = session_factory()
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="远控会话不存在",
        )
    db = factory()
    try:
        try:
            remote_svc.assert_device_log_stream_access(db, session_id, auth)
            remote_svc.request_device_log_control(
                db,
                session_id,
                auth,
                name="log.start",
                payload={"level": (level or "I").upper(), "tag": tag or ""},
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    finally:
        db.close()

    cursor, snapshot = device_log_bus.subscribe(session_id)

    async def _events():
        current = cursor
        try:
            yield "retry: 86400000\n: connected\n\n"
            for line in snapshot:
                yield f"data: {line}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                current, lines = await asyncio.to_thread(
                    device_log_bus.wait_lines, session_id, current, 15.0
                )
                if lines:
                    for line in lines:
                        yield f"data: {line}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            remaining = device_log_bus.unsubscribe(session_id)
            if remaining == 0:
                stop_db = factory()
                try:
                    remote_svc.request_device_log_control(
                        stop_db, session_id, auth, name="log.stop"
                    )
                except (LookupError, PermissionError, ValueError):
                    pass
                finally:
                    stop_db.close()

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Referrer-Policy": "no-referrer",
        },
    )
