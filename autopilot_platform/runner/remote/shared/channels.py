"""Runner 侧 Platform 远控通道适配器。

把 Hub 对 PlatformClient 的调用收敛为会话级组件，Android/iOS backend
无需感知 URL 与 session_id 拼接。
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

from .frame_bus import build_frame_message, pack_binary_frame
from .ws_client import RunnerRemoteWebSocket


class RemoteChannelClient(Protocol):
    def post_remote_signaling(
        self, session_id: str, path: str, body: dict[str, Any]
    ) -> None: ...

    def poll_remote_signaling(self, session_id: str) -> dict[str, Any]: ...

    def post_remote_media(self, session_id: str, body: dict[str, Any]) -> None: ...

    def poll_remote_media(self, session_id: str) -> dict[str, Any]: ...

    def post_remote_device_logs(
        self, session_id: str, body: dict[str, Any]
    ) -> None: ...


class RemoteChannels:
    """绑定单个 session_id 的信令与媒体通道。"""

    def __init__(self, client: RemoteChannelClient, session_id: str) -> None:
        self._client = client
        self.session_id = session_id
        self._ws: RunnerRemoteWebSocket | None = None
        base_url = str(getattr(client, "base_url", "") or "")
        api_token = str(getattr(client, "api_token", "") or "")
        if base_url and api_token:
            self._ws = RunnerRemoteWebSocket(base_url, api_token, session_id)
            self._ws.start()

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def post_signaling(self, path: str, body: dict[str, Any]) -> None:
        sent = False
        if self._ws is not None:
            sent = self._ws.send(
                "signaling",
                path.strip("/"),
                body,
                participant_id=str(body.get("participant_id") or ""),
            )
        if not sent:
            self._client.post_remote_signaling(self.session_id, path, body)

    def poll_signaling(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self._ws is not None:
            if self._ws.connected:
                messages.extend(self._ws.drain_signaling())
            else:
                # WS 重连窗口：仍 drain 本地队列，避免切换瞬间丢 offer/answer。
                messages.extend(self._ws.drain_signaling())
        out = self._client.poll_remote_signaling(self.session_id) or {}
        messages.extend(list(out.get("messages") or []))
        return messages

    def post_media(self, body: dict[str, Any]) -> None:
        name = str(body.get("type") or "media")
        packed = _binary_frame_from_body(body) if name == "frame" else None
        if packed is not None and self._ws is not None:
            if self._ws.send_binary(packed, drop_if_busy=True):
                return
            if self._ws.connected:
                return
        if packed is not None:
            jpeg = body.get("jpeg")
            if isinstance(jpeg, (bytes, bytearray)) and jpeg:
                self._client.post_remote_media(
                    self.session_id,
                    build_frame_message(
                        bytes(jpeg),
                        width=int(body.get("width") or 0),
                        height=int(body.get("height") or 0),
                        mime=str(body.get("mime") or "image/jpeg"),
                    ),
                )
                return
        drop_frame = name == "frame"
        if self._ws is not None:
            if self._ws.send("media", name, body, drop_if_busy=drop_frame):
                return
            if drop_frame and self._ws.connected:
                return
        self._client.post_remote_media(self.session_id, body)

    def poll_media(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self._ws is not None:
            messages.extend(self._ws.drain("media"))
            if self._ws.connected:
                messages.extend(self._ws.drain("command"))
                return messages
        out = self._client.poll_remote_media(self.session_id) or {}
        messages.extend(list(out.get("messages") or []))
        return messages

    def post_device_logs(self, lines: list[str]) -> None:
        """设备日志火管：始终走独立 HTTP，禁止混入 media/WS 画面通道。"""
        if not lines:
            return
        poster = getattr(self._client, "post_remote_device_logs", None)
        if poster is None:
            raise RuntimeError("Platform 客户端未实现设备日志投递")
        poster(self.session_id, {"lines": list(lines)})


def _binary_frame_from_body(body: dict[str, Any]) -> bytes | None:
    width = int(body.get("width") or 0)
    height = int(body.get("height") or 0)
    mime = str(body.get("mime") or "image/jpeg")
    jpeg = body.get("jpeg")
    if isinstance(jpeg, (bytes, bytearray)) and jpeg:
        return pack_binary_frame(bytes(jpeg), width=width, height=height, mime=mime)
    b64 = body.get("data_b64")
    if not isinstance(b64, str) or not b64.strip():
        return None
    try:
        raw = base64.b64decode(b64)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    return pack_binary_frame(raw, width=width, height=height, mime=mime)
