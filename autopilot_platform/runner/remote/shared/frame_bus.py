"""Runner ↔ Platform media 通道载荷约定（与 SDP 信令队列隔离）。

画面主路径：WebSocket **二进制** APJF 帧（无 base64）。
HTTP media-poll / WS 掉线兜底仍用 JSON + data_b64。
"""

from __future__ import annotations

import base64
import struct
import time
from typing import Any

FRAME_MAGIC = b"APJF"
FRAME_VERSION = 1
_HEADER = struct.Struct("!4sBBHH")  # magic, version, kind, width, height
_KIND_JPEG = 0
_KIND_PNG = 1
MAX_BINARY_FRAME_BYTES = 2_600_000


def build_frame_message(
    jpeg: bytes,
    *,
    width: int = 0,
    height: int = 0,
    mime: str = "image/jpeg",
) -> dict[str, Any]:
    """HTTP 兜底载荷；WS 在线时不要走这条（见 pack_binary_frame）。"""
    return {
        "type": "frame",
        "from_role": "runner",
        "mime": mime or "image/jpeg",
        "data_b64": base64.b64encode(jpeg).decode("ascii"),
        "width": int(width or 0),
        "height": int(height or 0),
        "ts": time.time(),
    }


def build_input_message(payload: dict[str, Any] | str) -> dict[str, Any]:
    """浏览器触控/按键；payload 可为 dict 或 JSON 字符串。"""
    return {
        "type": "input",
        "from_role": "browser",
        "payload": payload,
        "ts": time.time(),
    }


def _kind_for_mime(mime: str) -> int:
    return _KIND_PNG if "png" in (mime or "").lower() else _KIND_JPEG


def pack_binary_frame(
    image: bytes,
    *,
    width: int = 0,
    height: int = 0,
    mime: str = "image/jpeg",
) -> bytes:
    """APJF v1：10 字节头 + 原始 JPEG/PNG。"""
    return (
        _HEADER.pack(
            FRAME_MAGIC,
            FRAME_VERSION,
            _kind_for_mime(mime),
            max(0, int(width or 0)) & 0xFFFF,
            max(0, int(height or 0)) & 0xFFFF,
        )
        + image
    )


def unpack_binary_frame(raw: bytes) -> dict[str, Any] | None:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < _HEADER.size:
        return None
    magic, version, kind, width, height = _HEADER.unpack(raw[: _HEADER.size])
    if magic != FRAME_MAGIC or version != FRAME_VERSION:
        return None
    blob = bytes(raw[_HEADER.size :])
    mime = "image/png" if kind == _KIND_PNG else "image/jpeg"
    return {
        "type": "frame",
        "from_role": "runner",
        "mime": mime,
        "width": int(width),
        "height": int(height),
        "jpeg": blob,
        "ts": time.time(),
    }


def binary_frame_to_http_payload(raw: bytes) -> dict[str, Any] | None:
    """旁观仍走 HTTP poll 时，把二进制帧落到 data_b64 单槽。"""
    parsed = unpack_binary_frame(raw)
    if parsed is None:
        return None
    blob = parsed.pop("jpeg", b"")
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return None
    parsed["data_b64"] = base64.b64encode(bytes(blob)).decode("ascii")
    return parsed
