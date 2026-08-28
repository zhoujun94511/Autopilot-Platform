"""Phase 3 远控命令协议。

协议同时用于 WebSocket、WebRTC DataChannel 与 HTTP fallback。所有消息都带
request_id，长操作通过 progress/result/error 形成可关联的完整生命周期。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class RemoteChannel(str, Enum):
    SIGNALING = "signaling"
    MEDIA = "media"
    COMMAND = "command"
    EVENT = "event"


# WS / HTTP 回退与 DataChannel 共用。漏掉前缀会让命令在 Runner 侧被静默丢弃。
RELIABLE_COMMAND_PREFIXES = (
    "clipboard.",
    "file.",
    "app.",
    "stream.",
    "device.",
    "log.",
    "accessibility",
    "alert.",
    "input.",
)

# 对齐 Flask POST /api/devices/<udid>/button：Home/锁屏/音量是离散控制，不是触控流。
HARDWARE_BUTTON_COMMANDS = frozenset(
    {"home", "lock", "unlock", "press_button", "volumeup", "volumedown"}
)


def is_reliable_command_name(name: str) -> bool:
    text = str(name or "")
    return text.startswith(RELIABLE_COMMAND_PREFIXES) or text in HARDWARE_BUTTON_COMMANDS


def normalize_reliable_command(
    envelope: dict[str, Any],
) -> dict[str, Any] | None:
    """从 WS/HTTP 信封或裸事件里抽出可分发的可靠命令。"""
    env_type = str(envelope.get("type") or envelope.get("name") or "")
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        event = dict(payload)
        if not event.get("t"):
            if is_reliable_command_name(env_type):
                event["t"] = env_type
            elif envelope.get("name"):
                event["t"] = str(envelope["name"])
        if not event.get("request_id") and envelope.get("request_id"):
            event["request_id"] = str(envelope["request_id"])
    elif isinstance(envelope.get("t"), str):
        event = dict(envelope)
    else:
        return None
    command_type = str(event.get("t") or event.get("name") or env_type)
    if not is_reliable_command_name(command_type):
        return None
    event.setdefault("t", command_type)
    return event


class RemoteMessageType(str, Enum):
    REQUEST = "request"
    RESULT = "result"
    PROGRESS = "progress"
    ERROR = "error"
    EVENT = "event"
    PING = "ping"
    PONG = "pong"


class RemoteErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    NOT_SUPPORTED = "not_supported"
    BUSY = "busy"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    IO_ERROR = "io_error"
    SIGNATURE_MISMATCH = "signature_mismatch"
    DEVICE_OFFLINE = "device_offline"
    INTERNAL_ERROR = "internal_error"


@dataclass(slots=True)
class RemoteEnvelope:
    channel: str
    type: str
    name: str = ""
    request_id: str = field(default_factory=lambda: uuid4().hex)
    participant_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    progress: float | None = None
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "type": self.type,
            "name": self.name,
            "request_id": self.request_id,
            "participant_id": self.participant_id,
            "payload": dict(self.payload),
            "progress": self.progress,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RemoteEnvelope":
        return cls(
            channel=str(raw.get("channel") or ""),
            type=str(raw.get("type") or ""),
            name=str(raw.get("name") or ""),
            request_id=str(raw.get("request_id") or uuid4().hex),
            participant_id=str(raw.get("participant_id") or ""),
            payload=dict(raw.get("payload") or {}),
            progress=(
                float(raw["progress"])
                if raw.get("progress") is not None
                else None
            ),
            error_code=str(raw.get("error_code") or ""),
            error_message=str(raw.get("error_message") or ""),
        )


def result_for(
    request: RemoteEnvelope,
    payload: dict[str, Any] | None = None,
) -> RemoteEnvelope:
    return RemoteEnvelope(
        channel=request.channel,
        type=RemoteMessageType.RESULT.value,
        name=request.name,
        request_id=request.request_id,
        participant_id=request.participant_id,
        payload=dict(payload or {}),
    )


def error_for(
    request: RemoteEnvelope,
    code: RemoteErrorCode | str,
    message: str,
) -> RemoteEnvelope:
    return RemoteEnvelope(
        channel=request.channel,
        type=RemoteMessageType.ERROR.value,
        name=request.name,
        request_id=request.request_id,
        participant_id=request.participant_id,
        error_code=code.value if isinstance(code, RemoteErrorCode) else str(code),
        error_message=message,
    )
