"""设备远控会话：创建 / 信令中继 / Runner 拉令。

与 reservation 解耦：关闭远控 ≠ 释放占用；释放占用时应关闭远控。
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    DeviceRemoteCommandOut,
    DeviceRemoteCommandIn,
    DeviceRemoteCommandStatusOut,
    DeviceRemoteParticipantJoinIn,
    DeviceRemoteParticipantOut,
    DeviceRemotePrewarmHintOut,
    DeviceRemoteSessionCreate,
    DeviceRemoteSessionOut,
    DeviceRemoteTransportOut,
    IceServerOut,
    MediaMessageIn,
    MediaPollOut,
    SignalingMessageIn,
    SignalingPollOut,
)
from autopilot_platform.runner.remote.shared.frame_bus import binary_frame_to_http_payload

from ...auth import AuthContext
from ...core.models import (
    DeviceRemoteParticipantRow,
    DeviceRemoteSessionRow,
    DeviceReservationRow,
    DeviceRow,
    db_get,
    new_id,
    utcnow,
)
from ...core import api_messages as msg
from ...core.security import (
    create_device_log_stream_token,
    create_device_remote_token,
    create_turn_credentials,
)
from ...core.settings import is_production, stream_token_minutes, turn_enabled, turn_urls
from . import device_log_bus
from ...tenancy.projects import is_platform_admin
from .policy import can_user_manage_device, can_user_use_device
from .hub import get_remote_socket_hub

_ACTIVE = frozenset({"pending", "ready", "connected"})
_ANDROID_CAPS = ["mirror", "control", "webrtc", "android-scrcpy"]
_IOS_CAPS = ["mirror", "control", "mjpeg", "ios-wda"]
_PARTICIPANT_ACTIVE = frozenset({"joining", "connected"})
# 旁观可发的只读命令：画面外的设备信息/文件列举等，不含触控与写操作
_VIEWER_READONLY_COMMANDS = frozenset(
    {
        "device.info",
        "file.list",
        "file.stat",
        "file.pull",
        "app.list",
        "clipboard.get",
        "stream.stats",
    }
)


def viewer_may_issue_command(name: str) -> bool:
    return (name or "").strip() in _VIEWER_READONLY_COMMANDS


def command_names_from_envelope(message: dict[str, Any] | None) -> set[str]:
    """信封 name 与 payload.t 一并取出，避免只读名夹带写操作。"""
    data = message if isinstance(message, dict) else {}
    names: set[str] = set()
    top = str(data.get("name") or "").strip()
    if top:
        names.add(top)
    payload = data.get("payload")
    if isinstance(payload, dict):
        nested = str(payload.get("t") or payload.get("name") or "").strip()
        if nested:
            names.add(nested)
    return names


def command_name_from_envelope(message: dict[str, Any] | None) -> str:
    data = message if isinstance(message, dict) else {}
    payload = data.get("payload")
    if isinstance(payload, dict):
        nested = str(payload.get("t") or payload.get("name") or "").strip()
        if nested:
            return nested
    return str(data.get("name") or "").strip()


def viewer_may_issue_envelope(message: dict[str, Any] | None) -> bool:
    names = command_names_from_envelope(message)
    return bool(names) and all(viewer_may_issue_command(name) for name in names)


def max_remote_sessions_per_runner() -> int:
    """0 表示 Platform 不限制；默认 4 与 Runner AUTOPILOT_MAX_CONCURRENT_REMOTE 对齐。"""
    try:
        return max(0, min(32, int(os.getenv("MC_MAX_REMOTE_SESSIONS_PER_RUNNER", "4"))))
    except (TypeError, ValueError):
        return 4


def _count_active_remote_for_runner(db: Session, runner_id: str) -> int:
    rid = (runner_id or "").strip()
    if not rid:
        return 0
    rows = list(
        db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.runner_id == rid,
                DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE)),
            )
        ).all()
    )
    return len(rows)


def _ice_servers(row: DeviceRemoteSessionRow) -> list[IceServerOut]:
    urls = list(turn_urls())
    stun_urls = [url for url in urls if url.startswith(("stun:", "stuns:"))]
    relay_urls = [url for url in urls if url.startswith(("turn:", "turns:"))]
    out: list[IceServerOut] = []
    if stun_urls:
        out.append(IceServerOut(urls=stun_urls))
    if turn_enabled() and relay_urls:
        username, credential, _expires_at = create_turn_credentials(
            row.id,
            expires_at=row.expires_at,
        )
        out.append(
            IceServerOut(
                urls=relay_urls,
                username=username,
                credential=credential,
            )
        )
    return out


def _signaling_load(row: DeviceRemoteSessionRow) -> dict[str, Any]:
    try:
        raw = json.loads(row.signaling_json or "{}")
        return raw if isinstance(raw, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _signaling_save(row: DeviceRemoteSessionRow, data: dict[str, Any]) -> None:
    row.signaling_json = json.dumps(data, ensure_ascii=False)


def _enqueue(row: DeviceRemoteSessionRow, *, for_role: str, message: dict[str, Any]) -> None:
    data = _signaling_load(row)
    key = f"to_{for_role}"
    queue = list(data.get(key) or [])
    queue.append(message)
    # 防止无限堆积
    data[key] = queue[-50:]
    _signaling_save(row, data)


def _dequeue(
    row: DeviceRemoteSessionRow,
    *,
    for_role: str,
    participant_id: str = "",
) -> list[dict[str, Any]]:
    """browser 带 participant_id 时只取本路 SDP，其余留在队列给其他旁观/控制者。"""
    data = _signaling_load(row)
    key = f"to_{for_role}"
    queue = list(data.get(key) or [])
    pid = (participant_id or "").strip()
    if for_role != "browser" or not pid:
        data[key] = []
        _signaling_save(row, data)
        return queue
    mine: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for queued in queue:
        queued_pid = str(queued.get("participant_id") or "").strip()
        if not queued_pid or queued_pid == pid:
            mine.append(queued)
        else:
            rest.append(queued)
    data[key] = rest
    _signaling_save(row, data)
    return mine


def _caps_for_platform(platform: str) -> list[str]:
    p = (platform or "").strip().lower()
    if p == "ios":
        return list(_IOS_CAPS)
    if p == "android":
        return list(_ANDROID_CAPS)
    return ["mirror", "control"]


def _ensure_controller_participant(
    db: Session,
    row: DeviceRemoteSessionRow,
) -> DeviceRemoteParticipantRow:
    existing = _participant_for_user(db, row.id, row.user_id)
    if existing is not None:
        existing.role = "controller"
        existing.status = "connected"
        existing.last_seen_at = utcnow()
        return existing
    now = utcnow()
    participant = DeviceRemoteParticipantRow(
        id=new_id(),
        session_id=row.id,
        user_id=row.user_id,
        username=row.username or "",
        role="controller",
        connection_id=f"controller-{row.user_id}",
        status="connected",
        joined_at=now,
        last_seen_at=now,
    )
    db.add(participant)
    return participant


def _close_participants(
    db: Session,
    row: DeviceRemoteSessionRow,
    closed_at: Any,
) -> None:
    participants = list(
        db.scalars(
            select(DeviceRemoteParticipantRow).where(
                DeviceRemoteParticipantRow.session_id == row.id,
                DeviceRemoteParticipantRow.status.in_(
                    tuple(_PARTICIPANT_ACTIVE)
                ),
            )
        ).all()
    )
    for participant in participants:
        participant.status = "left"
        participant.left_at = closed_at
        participant.last_seen_at = closed_at
    event = {
        "channel": "event",
        "type": "event",
        "name": "session.closed",
        "request_id": "",
        "participant_id": "",
        "payload": {"status": row.status, "reason": row.error_message or ""},
    }
    socket_hub = get_remote_socket_hub()
    socket_hub.publish(row.id, event, target_role="browser")
    socket_hub.publish(row.id, event, target_role="runner")


def expire_remote_sessions(db: Session) -> int:
    now = utcnow()
    n = 0
    rows = list(
        db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE))
            )
        ).all()
    )
    for row in rows:
        exp = row.expires_at
        if exp is not None and exp.tzinfo is None and now.tzinfo is not None:
            exp = exp.replace(tzinfo=now.tzinfo)
        if exp is not None and exp <= now:
            row.status = "closed"
            row.closed_at = now
            row.error_message = row.error_message or "expired"
            _close_participants(db, row, now)
            n += 1
    if n:
        db.commit()
    return n


def _participant_for_user(
    db: Session,
    session_id: str,
    user_id: str,
) -> DeviceRemoteParticipantRow | None:
    if not user_id:
        return None
    return db.scalars(
        select(DeviceRemoteParticipantRow).where(
            DeviceRemoteParticipantRow.session_id == session_id,
            DeviceRemoteParticipantRow.user_id == user_id,
            DeviceRemoteParticipantRow.status.in_(tuple(_PARTICIPANT_ACTIVE)),
        )
    ).first()


def _session_out(
    db: Session,
    row: DeviceRemoteSessionRow,
    *,
    auth: AuthContext | None = None,
    include_token: bool = False,
) -> DeviceRemoteSessionOut:
    token = ""
    if include_token and auth and auth.kind == "user":
        token = create_device_remote_token(
            sub=auth.user_id,
            role=auth.role or "operator",
            username=auth.username,
            session_id=row.id,
            device_id=row.device_id,
            runner_id=row.runner_id,
        )
    participant_id = ""
    role_for_user = ""
    if auth and auth.kind == "runner":
        role_for_user = "controller"
    elif auth and auth.kind == "user":
        participant = _participant_for_user(db, row.id, auth.user_id)
        if participant is not None:
            participant_id = participant.id
            role_for_user = participant.role
        elif auth.user_id == row.user_id:
            role_for_user = "controller"
        else:
            # 非会话主人（含未入席的 platform admin GET）默认 viewer，禁止升格为可触控
            role_for_user = "viewer"
    viewer_count = len(
        list(
            db.scalars(
                select(DeviceRemoteParticipantRow).where(
                    DeviceRemoteParticipantRow.session_id == row.id,
                    DeviceRemoteParticipantRow.role == "viewer",
                    DeviceRemoteParticipantRow.status.in_(
                        tuple(_PARTICIPANT_ACTIVE)
                    ),
                )
            ).all()
        )
    )
    return DeviceRemoteSessionOut(
        id=row.id,
        device_id=row.device_id,
        runner_id=row.runner_id,
        udid=row.udid or "",
        platform=row.platform or "",
        reservation_id=row.reservation_id or "",
        user_id=row.user_id or "",
        username=row.username or "",
        status=row.status,
        capabilities=list(row.capabilities),
        error_message=row.error_message or "",
        created_at=row.created_at,
        expires_at=row.expires_at,
        closed_at=row.closed_at,
        access_token=token,
        signaling_base_path=f"/api/v1/device-remote-sessions/{row.id}",
        participant_id=participant_id,
        participant_role=role_for_user,
        viewer_count=viewer_count,
        max_viewers=int(
            getattr(row, "max_viewers", 5)
            if getattr(row, "max_viewers", None) is not None
            else 5
        ),
        ice_servers=_ice_servers(row),
        transport=DeviceRemoteTransportOut(
            signaling="ws",
            media="ws",
            command="ws",
            websocket_path=f"/api/v1/device-remote-sessions/{row.id}/ws",
        ),
    )


def _assert_session_access(
    db: Session, auth: AuthContext, row: DeviceRemoteSessionRow
) -> None:
    if is_platform_admin(auth):
        return
    if auth.kind == "runner":
        if is_production() and not (auth.runner_id or "").strip():
            raise PermissionError("生产环境拒绝无 scope 的全局 Runner Token 操作远控会话")
        if not auth.runner_id or auth.runner_id == row.runner_id:
            return
        raise PermissionError("无权操作该远控会话")
    if auth.kind == "user" and auth.user_id == row.user_id:
        return
    if auth.kind == "user" and _participant_for_user(db, row.id, auth.user_id):
        return
    raise PermissionError("无权操作该远控会话")


def close_active_remote_sessions_on_startup(
    db: Session, *, commit: bool = True
) -> int:
    """Platform 重启后关闭进行中远控，避免复用 stale signaling / Runner 侧旧 PC。"""
    now = utcnow()
    rows = list(
        db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE))
            )
        ).all()
    )
    for row in rows:
        row.status = "closed"
        row.closed_at = now
        row.error_message = "platform_restarted"
        row.signaling_json = "{}"
        _close_participants(db, row, now)
        device_log_bus.drop(row.id)
    if commit:
        db.commit()
    return len(rows)


def flush_browser_signaling_queue(
    db: Session,
    session_id: str,
    *,
    participant_id: str = "",
) -> int:
    """Browser WS 刚上线时补发 DB 中积压的 answer/ice（对齐 Runner channels 双读）。"""
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None or row.status not in _ACTIVE:
        return 0
    if not get_remote_socket_hub().has_target(session_id, "browser"):
        return 0
    msgs = _dequeue(row, for_role="browser", participant_id=participant_id)
    sent = 0
    hub = get_remote_socket_hub()
    for payload in msgs:
        msg_type = str(payload.get("type") or "").strip().lower()
        if msg_type not in ("offer", "answer", "ice"):
            continue
        envelope: dict[str, Any] = {
            "channel": "signaling",
            "type": "event",
            "name": msg_type,
            "participant_id": str(payload.get("participant_id") or participant_id),
            "payload": payload,
        }
        if hub.publish(
            session_id,
            envelope,
            target_role="browser",
            participant_id=participant_id,
        ):
            sent += 1
    db.commit()
    return sent


def create_remote_session(
    db: Session,
    device_id: str,
    body: DeviceRemoteSessionCreate,
    auth: AuthContext,
) -> DeviceRemoteSessionOut:
    expire_remote_sessions(db)
    if auth.kind != "user" or not auth.user_id:
        raise PermissionError("仅登录用户可开启远控")

    device = db_get(db, DeviceRow, device_id)
    if device is None:
        raise LookupError("设备不存在")
    if not can_user_use_device(db, auth, device):
        raise PermissionError("无权使用该设备")
    if device.admin_disabled:
        raise PermissionError("设备维护中，无法远控")
    if (device.busy_job_id or "").strip():
        raise PermissionError("设备正被任务占用，无法远控")

    res_id = (device.reservation_id or "").strip()
    if not res_id:
        raise PermissionError("请先占用设备再开启远控")
    reservation = db_get(db, DeviceReservationRow, res_id)
    if reservation is None or reservation.status != "active":
        raise PermissionError("设备占用已失效，请重新占用")
    if reservation.user_id != auth.user_id:
        raise PermissionError("仅占用人可开启远控")

    platform = (device.platform or "").strip().lower()
    if platform not in ("android", "ios"):
        raise PermissionError("当前仅支持 Android / iOS 远控")
    caps = _caps_for_platform(platform)

    existing = db.scalars(
        select(DeviceRemoteSessionRow).where(
            DeviceRemoteSessionRow.device_id == device.id,
            DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE)),
        )
    ).first()
    if existing is not None:
        if existing.user_id == auth.user_id:
            _ensure_controller_participant(db, existing)
            db.commit()
            return _session_out(db, existing, auth=auth, include_token=True)
        raise PermissionError("该设备已有进行中的远控会话")

    runner_id = (device.runner_id or "").strip()
    limit = max_remote_sessions_per_runner()
    if limit > 0 and runner_id:
        active_n = _count_active_remote_for_runner(db, runner_id)
        if active_n >= limit:
            raise PermissionError(
                f"Runner 远控并发已满（{active_n}/{limit}），请关闭其他会话或稍后再试"
            )

    now = utcnow()
    minutes = int(body.duration_minutes or 60)
    row = DeviceRemoteSessionRow(
        id=new_id(),
        device_id=device.id,
        runner_id=device.runner_id,
        udid=device.udid or "",
        platform=platform,
        reservation_id=res_id,
        user_id=auth.user_id,
        username=auth.username or "",
        status="pending",
        capabilities_json=json.dumps(caps, ensure_ascii=False),
        signaling_json="{}",
        max_viewers=int(body.max_viewers),
        created_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _ensure_controller_participant(db, row)
    db.commit()
    return _session_out(db, row, auth=auth, include_token=True)


def get_remote_session(
    db: Session, session_id: str, auth: AuthContext
) -> DeviceRemoteSessionOut:
    expire_remote_sessions(db)
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    return _session_out(
        db, row, auth=auth, include_token=(auth.kind == "user")
    )


def participant_role(
    db: Session,
    row: DeviceRemoteSessionRow,
    auth: AuthContext,
) -> str:
    """设备控制角色（触控/命令）。

    platform admin **不**自动升为 controller，避免运维账号误控真机。
    Runner Token 代表设备侧执行者，仍视为可投递控制面消息。
    """
    if auth.kind == "runner":
        return "controller"
    if auth.kind == "user":
        participant = _participant_for_user(db, row.id, auth.user_id)
        if participant is not None:
            return participant.role
        if auth.user_id == row.user_id:
            return "controller"
    return ""


def can_manage_remote_session(
    db: Session,
    row: DeviceRemoteSessionRow,
    auth: AuthContext,
) -> bool:
    """运维权：关闭会话、强踢、转移控制权。占用者(host)与当前 controller、platform admin。"""
    if is_platform_admin(auth):
        return True
    if auth.kind == "user" and auth.user_id == row.user_id:
        return True
    return participant_role(db, row, auth) == "controller"


def _participant_out(
    row: DeviceRemoteParticipantRow,
) -> DeviceRemoteParticipantOut:
    return DeviceRemoteParticipantOut(
        id=row.id,
        session_id=row.session_id,
        user_id=row.user_id,
        username=row.username or "",
        role=row.role,
        connection_id=row.connection_id or "",
        status=row.status,
        joined_at=row.joined_at,
        last_seen_at=row.last_seen_at,
        left_at=row.left_at,
    )


def _publish_peer_control(
    row: DeviceRemoteSessionRow,
    *,
    name: str,
    payload: dict[str, Any],
) -> None:
    """通知 Runner（拆 Peer）与在线 browser（角色/离开）。"""
    body = {"type": name, **payload}
    envelope = {
        "channel": "event",
        "type": "event",
        "name": name,
        "request_id": "",
        "participant_id": str(body.get("participant_id") or ""),
        "payload": body,
    }
    hub = get_remote_socket_hub()
    hub.publish(row.id, envelope, target_role="browser")
    hub.publish(row.id, envelope, target_role="runner")
    _enqueue(row, for_role="runner", message=body)


def join_remote_session(
    db: Session,
    session_id: str,
    body: DeviceRemoteParticipantJoinIn,
    auth: AuthContext,
) -> DeviceRemoteSessionOut:
    if auth.kind != "user" or not auth.user_id:
        raise PermissionError("仅登录用户可加入远控")
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    device = db_get(db, DeviceRow, row.device_id)
    if device is None or not can_user_use_device(db, auth, device):
        raise PermissionError("无权旁观该设备")
    if auth.user_id != row.user_id and not (
        is_platform_admin(auth) or can_user_manage_device(db, auth, device)
    ):
        raise PermissionError("仅管理员可旁观他人远控")
    if auth.user_id == row.user_id:
        # 仅会话控制者（占用人开出的主会话）在 join 时保持 controller。
        # platform admin 旁观走 viewer 名额，不自动夺取控制权。
        _ensure_controller_participant(db, row)
        db.commit()
        return _session_out(db, row, auth=auth, include_token=True)
    existing = _participant_for_user(db, row.id, auth.user_id)
    if existing is None:
        viewer_count = len(
            list(
                db.scalars(
                    select(DeviceRemoteParticipantRow).where(
                        DeviceRemoteParticipantRow.session_id == row.id,
                        DeviceRemoteParticipantRow.role == "viewer",
                        DeviceRemoteParticipantRow.status.in_(
                            tuple(_PARTICIPANT_ACTIVE)
                        ),
                    )
                ).all()
            )
        )
        if viewer_count >= int(row.max_viewers or 0):
            raise PermissionError("远控旁观人数已达上限")
        now = utcnow()
        existing = DeviceRemoteParticipantRow(
            id=new_id(),
            session_id=row.id,
            user_id=auth.user_id,
            username=auth.username or "",
            role="viewer",
            connection_id=(body.connection_id or new_id())[:128],
            status="connected",
            joined_at=now,
            last_seen_at=now,
        )
        db.add(existing)
    else:
        existing.status = "connected"
        existing.last_seen_at = utcnow()
        if body.connection_id:
            existing.connection_id = body.connection_id[:128]
    db.commit()
    return _session_out(db, row, auth=auth, include_token=True)


def join_device_remote_session(
    db: Session,
    device_id: str,
    body: DeviceRemoteParticipantJoinIn,
    auth: AuthContext,
) -> DeviceRemoteSessionOut:
    row = db.scalars(
        select(DeviceRemoteSessionRow).where(
            DeviceRemoteSessionRow.device_id == device_id,
            DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE)),
        )
    ).first()
    if row is None:
        raise LookupError("该设备没有进行中的远控会话")
    return join_remote_session(db, row.id, body, auth)


def list_remote_participants(
    db: Session,
    session_id: str,
    auth: AuthContext,
) -> list[DeviceRemoteParticipantOut]:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    participants = list(
        db.scalars(
            select(DeviceRemoteParticipantRow).where(
                DeviceRemoteParticipantRow.session_id == session_id,
                DeviceRemoteParticipantRow.status.in_(
                    tuple(_PARTICIPANT_ACTIVE)
                ),
            )
        ).all()
    )
    return [_participant_out(item) for item in participants]


def leave_remote_participant(
    db: Session,
    session_id: str,
    participant_id: str,
    auth: AuthContext,
) -> DeviceRemoteParticipantOut:
    session = db_get(db, DeviceRemoteSessionRow, session_id)
    participant = db_get(db, DeviceRemoteParticipantRow, participant_id)
    if session is None or participant is None or participant.session_id != session_id:
        raise LookupError("远控参与者不存在")
    can_manage = (
        is_platform_admin(auth)
        or auth.user_id == session.user_id
        or auth.user_id == participant.user_id
    )
    if auth.kind != "user" or not can_manage:
        raise PermissionError("无权移除该参与者")
    if participant.role == "controller" and auth.user_id != participant.user_id:
        raise PermissionError("请通过关闭会话结束控制者连接")
    participant.status = "left"
    participant.left_at = utcnow()
    participant.last_seen_at = participant.left_at
    _publish_peer_control(
        session,
        name="participant.left",
        payload={"participant_id": participant.id},
    )
    db.commit()
    db.refresh(participant)
    return _participant_out(participant)


def promote_remote_participant(
    db: Session,
    session_id: str,
    participant_id: str,
    auth: AuthContext,
) -> DeviceRemoteParticipantOut:
    session = db_get(db, DeviceRemoteSessionRow, session_id)
    target = db_get(db, DeviceRemoteParticipantRow, participant_id)
    if session is None or target is None or target.session_id != session_id:
        raise LookupError("远控参与者不存在")
    if not can_manage_remote_session(db, session, auth):
        raise PermissionError("仅控制者或平台管理员可转移控制权")
    if target.status not in _PARTICIPANT_ACTIVE:
        raise ValueError("目标参与者已离开")
    current = list(
        db.scalars(
            select(DeviceRemoteParticipantRow).where(
                DeviceRemoteParticipantRow.session_id == session_id,
                DeviceRemoteParticipantRow.role == "controller",
                DeviceRemoteParticipantRow.status.in_(
                    tuple(_PARTICIPANT_ACTIVE)
                ),
            )
        ).all()
    )
    for participant in current:
        if participant.id != target.id:
            participant.role = "viewer"
    target.role = "controller"
    target.last_seen_at = utcnow()
    # 不改 session.user_id：占用者仍是 host，交权只换 presenter。
    _publish_peer_control(
        session,
        name="control.transferred",
        payload={
            "participant_id": target.id,
            "controller_participant_id": target.id,
            "controller_user_id": target.user_id,
        },
    )
    db.commit()
    db.refresh(target)
    return _participant_out(target)


def close_remote_session(
    db: Session, session_id: str, auth: AuthContext, *, reason: str = ""
) -> DeviceRemoteSessionOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if not can_manage_remote_session(db, row, auth):
        raise PermissionError("旁观者不能关闭远控会话")
    if row.status in _ACTIVE:
        row.status = "closed"
        row.closed_at = utcnow()
        if reason:
            row.error_message = reason[:512]
        _close_participants(db, row, row.closed_at)
        db.commit()
        db.refresh(row)
        device_log_bus.drop(session_id)
    return _session_out(db, row, auth=auth, include_token=False)


def close_sessions_for_reservation(db: Session, reservation_id: str) -> int:
    """占用释放时关闭关联远控。"""
    rid = (reservation_id or "").strip()
    if not rid:
        return 0
    now = utcnow()
    n = 0
    rows = list(
        db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.reservation_id == rid,
                DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE)),
            )
        ).all()
    )
    for row in rows:
        row.status = "closed"
        row.closed_at = now
        row.error_message = row.error_message or "reservation_released"
        _close_participants(db, row, now)
        device_log_bus.drop(row.id)
        n += 1
    return n


def list_runner_commands(
    db: Session, auth: AuthContext, *, runner_id: str = ""
) -> list[DeviceRemoteCommandOut]:
    expire_remote_sessions(db)
    if auth.kind != "runner":
        raise PermissionError("仅 Runner Token 可拉取远控指令")
    rid = (runner_id or auth.runner_id or "").strip()
    if not rid:
        raise PermissionError("缺少 runner_id")
    if auth.runner_id and auth.runner_id != rid:
        raise PermissionError("Runner Token 与 runner_id 不匹配")
    rows = list(
        db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.runner_id == rid,
                DeviceRemoteSessionRow.status.in_(("pending", "ready", "connected")),
            )
        ).all()
    )
    return [
        DeviceRemoteCommandOut(
            session_id=r.id,
            device_id=r.device_id,
            udid=r.udid,
            platform=r.platform,
            status=r.status,
            capabilities=list(r.capabilities),
            expires_at=r.expires_at,
            ice_servers=_ice_servers(r),
        )
        for r in rows
    ]


def list_prewarm_hints(
    db: Session, auth: AuthContext, *, runner_id: str = ""
) -> list[DeviceRemotePrewarmHintOut]:
    """已占用、尚无 active 远控会话的设备 — Runner 占用后 soft prewarm。"""
    expire_remote_sessions(db)
    if auth.kind != "runner":
        raise PermissionError("仅 Runner Token 可拉取 prewarm 提示")
    rid = (runner_id or auth.runner_id or "").strip()
    if not rid:
        raise PermissionError("缺少 runner_id")
    if auth.runner_id and auth.runner_id != rid:
        raise PermissionError("Runner Token 与 runner_id 不匹配")

    devices = list(
        db.scalars(
            select(DeviceRow).where(
                DeviceRow.runner_id == rid,
                DeviceRow.reservation_id.isnot(None),
                DeviceRow.reservation_id != "",
            )
        ).all()
    )
    hints: list[DeviceRemotePrewarmHintOut] = []
    for device in devices:
        res_id = (device.reservation_id or "").strip()
        if not res_id:
            continue
        reservation = db_get(db, DeviceReservationRow, res_id)
        if reservation is None or reservation.status != "active":
            continue
        platform = (device.platform or "").strip().lower()
        if platform not in ("android", "ios"):
            continue
        existing = db.scalars(
            select(DeviceRemoteSessionRow).where(
                DeviceRemoteSessionRow.device_id == device.id,
                DeviceRemoteSessionRow.status.in_(tuple(_ACTIVE)),
            )
        ).first()
        if existing is not None:
            continue
        hints.append(
            DeviceRemotePrewarmHintOut(
                device_id=device.id,
                udid=device.udid or "",
                platform=platform,
            )
        )
    return hints


def update_runner_status(
    db: Session,
    session_id: str,
    auth: AuthContext,
    *,
    status: str,
    error_message: str = "",
    capabilities: list[str] | None = None,
) -> DeviceRemoteSessionOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    st = (status or "").strip().lower()
    if st not in ("ready", "connected", "failed", "closed"):
        raise ValueError("非法 status")
    row.status = st
    if error_message:
        row.error_message = error_message[:512]
    if capabilities is not None:
        row.capabilities = capabilities
    if st in ("failed", "closed"):
        row.closed_at = utcnow()
    db.commit()
    db.refresh(row)
    return _session_out(db, row)


def post_signaling(
    db: Session, session_id: str, auth: AuthContext, body: SignalingMessageIn
) -> dict[str, str]:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")

    role = (body.from_role or "browser").strip().lower()
    if auth.kind == "runner":
        role = "runner"
    elif auth.kind == "user":
        role = "browser"
    if role not in ("browser", "runner"):
        raise ValueError("from_role 须为 browser 或 runner")

    msg_type = (body.type or "").strip().lower()
    if msg_type not in ("offer", "answer", "ice"):
        raise ValueError("type 须为 offer | answer | ice")

    peer = "runner" if role == "browser" else "browser"
    pid = body.participant_id or ""
    live_role = body.participant_role or ""
    if role == "browser" and auth.kind == "user":
        participant = _participant_for_user(db, row.id, auth.user_id)
        pid = participant.id if participant is not None else ""
        live_role = participant.role if participant is not None else (
            participant_role(db, row, auth) or ""
        )
    payload: dict[str, Any] = {
        "type": msg_type,
        "from_role": role,
        "sdp": body.sdp or "",
        "candidate": body.candidate or {},
        "participant_id": pid,
        "participant_role": live_role,
    }
    hub = get_remote_socket_hub()
    envelope: dict[str, Any] = {
        "channel": "signaling",
        "type": "event",
        "name": msg_type,
        "participant_id": pid,
        "payload": payload,
    }
    if peer == "browser":
        # 浏览器常 WS 晚于 offer：answer/ice 必须入队供 poll 消费。
        _enqueue(row, for_role=peer, message=payload)
        hub.publish(
            session_id,
            envelope,
            target_role=peer,
            participant_id=pid,
        )
    elif hub.has_target(session_id, peer):
        # Runner 已 WS 在线：直推 envelope（Runner drain_signaling 消费），不写 DB。
        hub.publish(
            session_id,
            envelope,
            target_role=peer,
            participant_id=pid,
        )
    else:
        # Runner 离线 / 跨 worker：HTTP poll 兜底。
        _enqueue(row, for_role=peer, message=payload)
    db.commit()
    return {"ok": "true"}


def poll_signaling(
    db: Session, session_id: str, auth: AuthContext
) -> SignalingPollOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    role = "runner" if auth.kind == "runner" else "browser"
    pid = ""
    if role == "browser" and auth.kind == "user":
        participant = _participant_for_user(db, row.id, auth.user_id)
        pid = participant.id if participant is not None else ""
    msgs = _dequeue(row, for_role=role, participant_id=pid)
    db.commit()
    return SignalingPollOut(messages=msgs, session_status=row.status)


_MEDIA_FRAME_SLOT = "media_frame_slot"
_MEDIA_FRAME_SEQ = "media_frame_seq"
_MEDIA_FRAME_ACK = "media_frame_ack"


def _active_participant_ids(db: Session, session_id: str) -> set[str]:
    return {
        participant.id
        for participant in db.scalars(
            select(DeviceRemoteParticipantRow).where(
                DeviceRemoteParticipantRow.session_id == session_id,
                DeviceRemoteParticipantRow.status.in_(tuple(_PARTICIPANT_ACTIVE)),
            )
        ).all()
        if participant.id
    }


def _http_frame_slot_needed(db: Session, row: DeviceRemoteSessionRow) -> bool:
    """有人走 HTTP 拉 MJPEG 时才落库；全员 browser WS 在线则跳过，避免 15fps 写库。"""
    ws_ids = get_remote_socket_hub().connected_browser_participant_ids(row.id)
    if not ws_ids:
        return True
    active = _active_participant_ids(db, row.id)
    if not active:
        return True
    return not active.issubset(ws_ids)


def _media_enqueue(
    row: DeviceRemoteSessionRow, *, for_role: str, message: dict[str, Any]
) -> None:
    """media 与 SDP 分离。

    browser 的 JPEG **只存最新一帧**（不按旁观人数复制），用 per-consumer seq
    游标 fan-out；input/command 仍走消费即删队列（Runner 只有一路）。
    """
    data = _signaling_load(row)
    key = f"media_to_{for_role}"
    queued_type = str(message.get("type") or "")
    if queued_type == "frame" and for_role == "browser":
        seq = int(data.get(_MEDIA_FRAME_SEQ) or 0) + 1
        data[_MEDIA_FRAME_SEQ] = seq
        data[_MEDIA_FRAME_SLOT] = message
        leftover = [
            item
            for item in list(data.get(key) or [])
            if str(item.get("type") or "") != "frame"
        ]
        data[key] = leftover
        _signaling_save(row, data)
        return
    queue = list(data.get(key) or [])
    queue.append(message)
    data[key] = queue[-30:]
    _signaling_save(row, data)


def _media_dequeue(
    row: DeviceRemoteSessionRow,
    *,
    for_role: str,
    consumer_id: str = "",
) -> list[dict[str, Any]]:
    data = _signaling_load(row)
    key = f"media_to_{for_role}"
    queued = list(data.get(key) or [])
    if for_role != "browser":
        data[key] = []
        _signaling_save(row, data)
        return queued

    frames = [item for item in queued if str(item.get("type") or "") == "frame"]
    events = [item for item in queued if str(item.get("type") or "") != "frame"]
    data[key] = []
    if frames and not isinstance(data.get(_MEDIA_FRAME_SLOT), dict):
        data[_MEDIA_FRAME_SLOT] = frames[-1]
        data[_MEDIA_FRAME_SEQ] = max(1, int(data.get(_MEDIA_FRAME_SEQ) or 0))

    out: list[dict[str, Any]] = list(events)
    cid = (consumer_id or "").strip() or "browser"
    slot = data.get(_MEDIA_FRAME_SLOT)
    frame_seq = int(data.get(_MEDIA_FRAME_SEQ) or 0)
    acks = dict(data.get(_MEDIA_FRAME_ACK) or {})
    last = int(acks.get(cid) or 0)
    if isinstance(slot, dict) and frame_seq > last:
        out.append(slot)
        acks[cid] = frame_seq
        if len(acks) > 24:
            ranked = sorted(acks.items(), key=lambda item: item[1], reverse=True)
            acks = dict(ranked[:24])
            acks[cid] = frame_seq
        data[_MEDIA_FRAME_ACK] = acks
    _signaling_save(row, data)
    return out


def _command_statuses(row: DeviceRemoteSessionRow) -> dict[str, dict[str, Any]]:
    data = _signaling_load(row)
    raw = data.get("command_statuses")
    return dict(raw) if isinstance(raw, dict) else {}


def _save_command_status(
    row: DeviceRemoteSessionRow,
    request_id: str,
    status: dict[str, Any],
) -> None:
    data = _signaling_load(row)
    statuses = _command_statuses(row)
    statuses[request_id] = status
    data["command_statuses"] = dict(list(statuses.items())[-100:])
    _signaling_save(row, data)


def post_command(
    db: Session,
    session_id: str,
    auth: AuthContext,
    body: DeviceRemoteCommandIn,
) -> DeviceRemoteCommandStatusOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if participant_role(db, row, auth) != "controller":
        if not viewer_may_issue_command(body.name):
            raise PermissionError("旁观者为只读，不能执行命令")
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    request_id = (body.request_id or new_id())[:128]
    event = {
        "t": body.name,
        "name": body.name,
        "request_id": request_id,
        **dict(body.payload or {}),
    }
    envelope = {
        "channel": "command",
        "type": "request",
        "name": body.name,
        "request_id": request_id,
        "participant_id": "",
        "payload": event,
    }
    if not get_remote_socket_hub().publish(
        session_id, envelope, target_role="runner"
    ):
        _media_enqueue(row, for_role="runner", message=event)
    status = {
        "request_id": request_id,
        "name": body.name,
        "status": "accepted",
        "progress": 0,
        "result": {},
        "error_code": "",
        "error_message": "",
    }
    _save_command_status(row, request_id, status)
    db.commit()
    return DeviceRemoteCommandStatusOut(**status)


def get_command_status(
    db: Session,
    session_id: str,
    request_id: str,
    auth: AuthContext,
) -> DeviceRemoteCommandStatusOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    status = _command_statuses(row).get(request_id)
    if status is None:
        raise LookupError("远控命令不存在")
    return DeviceRemoteCommandStatusOut(**status)


def post_media(
    db: Session, session_id: str, auth: AuthContext, body: MediaMessageIn
) -> dict[str, str]:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")

    role = (body.from_role or "browser").strip().lower()
    if auth.kind == "runner":
        role = "runner"
    elif auth.kind == "user":
        role = "browser"
    if role not in ("browser", "runner"):
        raise ValueError("from_role 须为 browser 或 runner")

    msg_type = (body.type or "").strip().lower()
    if msg_type not in ("frame", "input", "command", "command_reply"):
        raise ValueError("type 须为 frame | input | command | command_reply")
    if msg_type == "frame" and role != "runner":
        raise ValueError("仅 Runner 可推送 frame")
    if msg_type == "input" and role != "browser":
        raise ValueError("仅浏览器可推送 input")
    live_role = participant_role(db, row, auth)
    if role == "browser" and msg_type == "input" and live_role != "controller":
        raise PermissionError("旁观者为只读，不能控制设备")
    if role == "browser" and msg_type == "command" and live_role != "controller":
        payload = body.payload if isinstance(body.payload, dict) else {}
        cmd = str(payload.get("t") or payload.get("name") or "").strip()
        if not viewer_may_issue_command(cmd):
            raise PermissionError("旁观者为只读，不能控制设备")
    if msg_type == "frame" and not (body.data_b64 or "").strip():
        raise ValueError("frame 缺少 data_b64")

    peer = "browser" if role == "runner" else "runner"
    payload: dict[str, Any] = {
        "type": msg_type,
        "from_role": role,
        "mime": body.mime or "image/jpeg",
        "data_b64": body.data_b64 or "",
        "width": int(body.width or 0),
        "height": int(body.height or 0),
        "ts": float(body.ts or 0),
        "payload": body.payload if body.payload is not None else {},
    }
    # 粗限：单帧 base64 过大直接拒（约 2.5MB 原始）
    if msg_type == "frame" and len(payload["data_b64"]) > 3_500_000:
        raise ValueError("frame 过大")
    if msg_type == "command_reply" and isinstance(body.payload, dict):
        request_id = str(body.payload.get("request_id") or "")
        if request_id:
            reply_type = str(body.payload.get("t") or "")
            is_error = reply_type == "error" or reply_type.endswith(".error")
            is_progress = (
                reply_type.endswith(".progress")
                or reply_type.endswith(".ready")
                or reply_type.endswith(".chunk")
            )
            result_payload = dict(body.payload)
            if reply_type.endswith(".chunk"):
                result_payload.pop("data", None)
            status = {
                "request_id": request_id,
                "name": str(body.payload.get("for") or ""),
                "status": (
                    "failed"
                    if is_error
                    else "running"
                    if is_progress
                    else "completed"
                ),
                "progress": float(body.payload.get("progress") or 0),
                "result": result_payload,
                "error_code": str(body.payload.get("error_code") or ""),
                "error_message": str(body.payload.get("error") or ""),
            }
            _save_command_status(row, request_id, status)
    ws_payload = {
        "channel": "media" if msg_type in ("frame", "input") else "command",
        "type": "event" if msg_type in ("frame", "input") else "result",
        "name": msg_type,
        "request_id": str(
            payload.get("payload", {}).get("request_id", "")
            if isinstance(payload.get("payload"), dict)
            else ""
        ),
        "payload": payload,
    }
    published = get_remote_socket_hub().publish(
        session_id,
        ws_payload,
        target_role=peer,
    )
    persist_http_frame = (
        peer == "browser"
        and msg_type == "frame"
        and _http_frame_slot_needed(db, row)
    )
    if persist_http_frame or not published:
        _media_enqueue(row, for_role=peer, message=payload)
    if persist_http_frame or not published or msg_type == "command_reply":
        db.commit()
    return {"ok": "true"}


def poll_media(db: Session, session_id: str, auth: AuthContext) -> MediaPollOut:
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    role = "runner" if auth.kind == "runner" else "browser"
    consumer_id = ""
    if role == "browser" and auth.kind == "user":
        participant = _participant_for_user(db, row.id, auth.user_id)
        consumer_id = (
            participant.id if participant is not None else f"user:{auth.user_id}"
        )
    msgs = _media_dequeue(row, for_role=role, consumer_id=consumer_id)
    db.commit()
    return MediaPollOut(messages=msgs, session_status=row.status)


def enqueue_ws_fallback(
    db: Session,
    session_id: str,
    auth: AuthContext,
    message: dict[str, Any],
    *,
    target_role: str,
) -> None:
    """WebSocket 对端离线时将 envelope 投递到旧 HTTP 队列。"""
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if target_role not in ("browser", "runner"):
        raise ValueError("非法 target_role")
    channel = str(message.get("channel") or "")
    if channel == "signaling":
        payload = dict(message.get("payload") or message)
        payload.setdefault("participant_id", message.get("participant_id") or "")
        payload.setdefault("participant_role", message.get("participant_role") or "")
        _enqueue(row, for_role=target_role, message=payload)
    else:
        payload = message.get("payload")
        queued = dict(payload) if isinstance(payload, dict) else dict(message)
        _media_enqueue(row, for_role=target_role, message=queued)
    db.commit()


def maybe_persist_http_browser_media(
    db: Session,
    session_id: str,
    auth: AuthContext,
    message: dict[str, Any],
) -> None:
    """Runner WS 已 fan-out 时，给仍走 HTTP 的旁观补最新一帧（不复制多份 JPEG）。"""
    payload = message.get("payload")
    queued = dict(payload) if isinstance(payload, dict) else dict(message)
    if str(queued.get("type") or message.get("name") or "") != "frame":
        return
    queued.setdefault("type", "frame")
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None or row.status not in _ACTIVE:
        return
    _assert_session_access(db, auth, row)
    if not _http_frame_slot_needed(db, row):
        return
    _media_enqueue(row, for_role="browser", message=queued)
    db.commit()


def enqueue_ws_binary_frame_fallback(
    db: Session,
    session_id: str,
    auth: AuthContext,
    packed: bytes,
) -> None:
    """Runner 二进制画面在无 browser WS 时落入 HTTP 单槽。"""
    queued = binary_frame_to_http_payload(packed)
    if queued is None:
        return
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    _media_enqueue(row, for_role="browser", message=queued)
    db.commit()


def maybe_persist_http_browser_binary_frame(
    db: Session,
    session_id: str,
    auth: AuthContext,
    packed: bytes,
) -> None:
    queued = binary_frame_to_http_payload(packed)
    if queued is None:
        return
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None or row.status not in _ACTIVE:
        return
    _assert_session_access(db, auth, row)
    if not _http_frame_slot_needed(db, row):
        return
    _media_enqueue(row, for_role="browser", message=queued)
    db.commit()


def issue_device_log_stream_token(
    db: Session, session_id: str, auth: AuthContext
) -> dict[str, Any]:
    if auth.kind != "user":
        raise PermissionError(msg.AUTH_USER_LOGIN_REQUIRED)
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    ttl_min = stream_token_minutes()
    return {
        "access_token": create_device_log_stream_token(
            sub=auth.user_id,
            role=auth.role,
            username=auth.username,
            session_id=session_id,
            minutes=ttl_min,
        ),
        "expires_in": ttl_min * 60,
        "token_type": "device_log_stream",
    }


def ingest_device_logs(
    db: Session,
    session_id: str,
    auth: AuthContext,
    lines: list[str],
) -> dict[str, int]:
    if auth.kind != "runner":
        raise PermissionError("仅 Runner 可投递设备日志")
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    accepted = device_log_bus.append(session_id, list(lines or []))
    return {"accepted": accepted}


def request_device_log_control(
    db: Session,
    session_id: str,
    auth: AuthContext,
    *,
    name: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """向 Runner 投递 log.start/stop/clear。火管数据不走此通道。"""
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    _assert_session_access(db, auth, row)
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    command = (name or "").strip()
    if command == "log.clear" and participant_role(db, row, auth) != "controller":
        raise PermissionError("旁观者为只读，不能清空设备日志")
    if command not in ("log.start", "log.stop", "log.clear"):
        raise ValueError("不支持的日志控制命令")
    event = {
        "t": command,
        "name": command,
        "request_id": new_id(),
        **dict(payload or {}),
    }
    envelope = {
        "channel": "command",
        "type": "request",
        "name": command,
        "request_id": event["request_id"],
        "participant_id": "",
        "payload": event,
    }
    if not get_remote_socket_hub().publish(
        session_id, envelope, target_role="runner"
    ):
        _media_enqueue(row, for_role="runner", message=event)
    db.commit()


def assert_device_log_stream_access(
    db: Session, session_id: str, auth: AuthContext
) -> None:
    if auth.stream_session_id and auth.stream_session_id != session_id:
        raise PermissionError(msg.DEVICE_LOG_STREAM_TOKEN_SCOPED)
    if not auth.stream_session_id:
        raise PermissionError(msg.DEVICE_LOG_STREAM_TOKEN_SCOPED)
    row = db_get(db, DeviceRemoteSessionRow, session_id)
    if row is None:
        raise LookupError("远控会话不存在")
    if row.status not in _ACTIVE:
        raise PermissionError("远控会话已结束")
    # 短时票已绑定 session_id；再核对用户仍可访问该会话（占用释放后拒绝）。
    if auth.kind == "user" and auth.user_id:
        if auth.user_id == row.user_id:
            return
        if _participant_for_user(db, row.id, auth.user_id):
            return
        if is_platform_admin(auth):
            return
        raise PermissionError("无权操作该远控会话")

