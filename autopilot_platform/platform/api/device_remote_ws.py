"""远控原生 WebSocket：信令、iOS 媒体、命令与事件统一中继。"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from autopilot_platform.runner.remote.shared.frame_bus import (
    MAX_BINARY_FRAME_BYTES,
    unpack_binary_frame,
)

from ..auth import (
    AuthContext,
    auth_from_device_remote_token,
    auth_runner_api_token,
)
from ..core.db import get_session
from ..core.settings import is_production
from ..services.remote import sessions as remote_svc
from ..services.remote.hub import RemoteSocket, get_remote_socket_hub

router = APIRouter(tags=["device-remote-ws"])
_log = logging.getLogger(__name__)

_BROWSER_AUTH_TIMEOUT_S = 5.0


def _runner_authenticate(websocket: WebSocket, db: Session) -> AuthContext:
    return auth_runner_api_token(
        websocket.headers.get("x-api-token", ""),
        db,
    )


def _browser_token_from_query(websocket: WebSocket) -> str:
    return (websocket.query_params.get("access_token") or "").strip()


def _extract_browser_token(message: dict) -> str:
    if str(message.get("type") or "") == "auth":
        return str(
            message.get("access_token")
            or (message.get("payload") or {}).get("access_token")
            or ""
        ).strip()
    if str(message.get("name") or "") == "auth":
        payload = message.get("payload")
        if isinstance(payload, dict):
            return str(payload.get("access_token") or "").strip()
        return str(message.get("access_token") or "").strip()
    return ""


async def _browser_authenticate(
    websocket: WebSocket,
    session_id: str,
) -> tuple[AuthContext, str]:
    """优先首帧 auth；query access_token 仅作兼容回退（会进代理日志）。"""
    query_token = _browser_token_from_query(websocket)
    if query_token:
        if is_production():
            raise HTTPException(
                status_code=401,
                detail="生产环境禁止 query access_token，请使用首帧 auth",
            )
        _log.warning(
            "device-remote WS used query access_token session=%s (prefer first-frame auth)",
            session_id[:12],
        )
        return auth_from_device_remote_token(query_token, session_id), "query"

    try:
        raw = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=_BROWSER_AUTH_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, WebSocketDisconnect) as exc:
        raise HTTPException(status_code=401, detail="远控 WS 鉴权超时") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=401, detail="远控 WS 鉴权帧无效")
    token = _extract_browser_token(raw)
    if not token:
        raise HTTPException(status_code=401, detail="远控 WS 缺少 access_token")
    return auth_from_device_remote_token(token, session_id), "first_frame"


async def _safe_close(websocket: WebSocket, *, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason[:120])
    except (RuntimeError, OSError, WebSocketDisconnect):
        pass


def _parse_ws_json_object(text: Any) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _envelope_payload(message: dict[str, Any]) -> dict[str, Any]:
    raw = message.get("payload")
    if isinstance(raw, dict):
        return raw
    payload: dict[str, Any] = {}
    message["payload"] = payload
    return payload


async def _live_session_or_close(
    websocket: WebSocket,
    db: Session,
    session_id: str,
    auth: AuthContext,
) -> Any | None:
    try:
        return remote_svc.get_remote_session(db, session_id, auth)
    except (PermissionError, LookupError) as exc:
        await websocket.close(code=4403, reason=str(exc))
        return None


@router.websocket("/device-remote-sessions/{session_id}/ws")
async def device_remote_websocket(
    websocket: WebSocket,
    session_id: str,
    db: Session = Depends(get_session),
) -> None:
    role = (websocket.query_params.get("role") or "browser").strip().lower()
    if role not in {"browser", "runner"}:
        await websocket.close(code=4400, reason="invalid role")
        return

    connection_id = websocket.query_params.get("connection_id", "") or uuid4().hex
    hub = get_remote_socket_hub()
    socket: RemoteSocket | None = None
    participant_id = ""
    auth_via = "header"

    try:
        if role == "runner":
            auth = _runner_authenticate(websocket, db)
            # 校验会话可见性；runner 无 participant_id。
            remote_svc.get_remote_session(db, session_id, auth)
            socket = await hub.connect(
                session_id,
                websocket,
                role=role,
                participant_id="",
                connection_id=connection_id,
            )
        else:
            # 先 accept，再首帧鉴权，避免把 JWT 放进 URL query。
            socket = await hub.connect(
                session_id,
                websocket,
                role=role,
                participant_id="",
                connection_id=connection_id,
            )
            auth, auth_via = await _browser_authenticate(websocket, session_id)
            session_info = remote_svc.get_remote_session(db, session_id, auth)
            participant_id = session_info.participant_id or ""
            socket.participant_id = participant_id
    except HTTPException as exc:
        if socket is not None:
            hub.disconnect(session_id, socket)
        await _safe_close(websocket, code=4401, reason=str(exc.detail))
        return
    except PermissionError as exc:
        if socket is not None:
            hub.disconnect(session_id, socket)
        await _safe_close(websocket, code=4403, reason=str(exc))
        return
    except LookupError as exc:
        if socket is not None:
            hub.disconnect(session_id, socket)
        await _safe_close(websocket, code=4404, reason=str(exc))
        return

    await websocket.send_json(
        {
            "channel": "event",
            "type": "event",
            "name": "transport.ready",
            "request_id": "",
            "participant_id": participant_id,
            "payload": {
                "transport": "ws",
                "connection_id": connection_id,
                "role": role,
                "auth_via": auth_via if role == "browser" else "header",
            },
        }
    )
    if role == "browser":
        try:
            flushed = remote_svc.flush_browser_signaling_queue(
                db,
                session_id,
                participant_id=participant_id,
            )
            if flushed:
                _log.info(
                    "device-remote WS flushed %s signaling message(s) session=%s",
                    flushed,
                    session_id[:12],
                )
        except Exception as flush_err:  # noqa: BLE001
            _log.debug("signaling flush on connect: %s", flush_err)
    try:
        while True:
            incoming = await websocket.receive()
            if incoming.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(incoming.get("code") or 1000)
            raw_bytes = incoming.get("bytes")
            if raw_bytes is not None:
                if role != "runner":
                    continue
                if (
                    not isinstance(raw_bytes, (bytes, bytearray))
                    or len(raw_bytes) > MAX_BINARY_FRAME_BYTES
                    or unpack_binary_frame(bytes(raw_bytes)) is None
                ):
                    continue
                packed = bytes(raw_bytes)
                delivered = await hub.broadcast_bytes(
                    session_id,
                    packed,
                    target_role="browser",
                    exclude=socket,
                )
                if not delivered:
                    remote_svc.enqueue_ws_binary_frame_fallback(
                        db, session_id, auth, packed
                    )
                else:
                    remote_svc.maybe_persist_http_browser_binary_frame(
                        db, session_id, auth, packed
                    )
                continue
            text = incoming.get("text")
            if not text:
                continue
            message = _parse_ws_json_object(text)
            if message is None:
                continue
            if message.get("type") == "ping":
                await websocket.send_json(
                    {
                        **message,
                        "type": "pong",
                        "name": "transport.pong",
                    }
                )
                continue
            channel = str(message.get("channel") or "")
            # ACL 必须按消息实时判定：控制权 promote 后，旧 controller 连接不能继续发控制帧。
            if role == "browser" and channel in {"media", "command"}:
                db.expire_all()
                live = await _live_session_or_close(
                    websocket, db, session_id, auth
                )
                if live is None:
                    return
                if live.participant_role != "controller":
                    allow_readonly = (
                        channel == "command"
                        and remote_svc.viewer_may_issue_envelope(message)
                    )
                    if not allow_readonly:
                        await websocket.send_json(
                            {
                                "channel": "event",
                                "type": "error",
                                "name": str(message.get("name") or ""),
                                "request_id": str(message.get("request_id") or ""),
                                "participant_id": participant_id,
                                "payload": {},
                                "error_code": "forbidden",
                                "error_message": "旁观者为只读，不能控制设备",
                            }
                        )
                        continue
            message["from_role"] = role
            if role == "browser":
                # 禁止客户端伪造他人 participant_id / 把旁观标成 controller。
                message["participant_id"] = participant_id
                payload = _envelope_payload(message)
                payload["participant_id"] = participant_id
                if channel == "signaling":
                    db.expire_all()
                    live = await _live_session_or_close(
                        websocket, db, session_id, auth
                    )
                    if live is None:
                        return
                    payload["participant_role"] = live.participant_role
                    message["participant_role"] = live.participant_role
            else:
                message.setdefault("participant_id", "")
            target = "runner" if role == "browser" else "browser"
            delivered = await hub.broadcast(
                session_id,
                message,
                target_role=target,
                participant_id=str(message.get("participant_id") or ""),
                exclude=socket,
            )
            if not delivered:
                # 对端不在线时持久化到原有 DB 队列，HTTP 客户端可继续消费。
                remote_svc.enqueue_ws_fallback(
                    db,
                    session_id,
                    auth,
                    message,
                    target_role=target,
                )
            elif role == "runner" and target == "browser":
                remote_svc.maybe_persist_http_browser_media(
                    db, session_id, auth, message
                )
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(session_id, socket)
