"""远控会话协议（Android WebRTC / iOS MJPEG 共用生命周期约定）。"""

from __future__ import annotations

from typing import Protocol


class RemoteMediaSession(Protocol):
    """Hub 管理的本机远控会话最小接口。"""

    session_id: str
    udid: str

    def start(self) -> None: ...

    def stop(self) -> None: ...
