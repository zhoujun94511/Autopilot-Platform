"""进程内远控 WebSocket 中继。

DB 队列仍是 HTTP fallback；该 hub 只负责在线连接的低延迟投递。多 worker
部署时应保持 sticky session，未命中本进程的消息会自然回落到 DB poll。
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(slots=True)
class RemoteSocket:
    websocket: WebSocket
    role: str
    participant_id: str
    connection_id: str
    loop: asyncio.AbstractEventLoop


class DeviceRemoteSocketHub:
    def __init__(self) -> None:
        self._guard = threading.RLock()
        self._sessions: dict[str, dict[str, RemoteSocket]] = {}

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket,
        *,
        role: str,
        participant_id: str = "",
        connection_id: str = "",
    ) -> RemoteSocket:
        await websocket.accept()
        socket = RemoteSocket(
            websocket=websocket,
            role=role,
            participant_id=participant_id,
            connection_id=connection_id,
            loop=asyncio.get_running_loop(),
        )
        key = connection_id or participant_id or f"{role}:{id(websocket)}"
        with self._guard:
            self._sessions.setdefault(session_id, {})[key] = socket
        return socket

    def disconnect(self, session_id: str, socket: RemoteSocket) -> None:
        with self._guard:
            peers = self._sessions.get(session_id)
            if not peers:
                return
            for key, current in list(peers.items()):
                if current is socket:
                    peers.pop(key, None)
            if not peers:
                self._sessions.pop(session_id, None)

    def has_target(self, session_id: str, target_role: str) -> bool:
        with self._guard:
            return any(
                peer.role == target_role
                for peer in self._sessions.get(session_id, {}).values()
            )

    def connected_browser_participant_ids(self, session_id: str) -> frozenset[str]:
        with self._guard:
            return frozenset(
                peer.participant_id
                for peer in self._sessions.get(session_id, {}).values()
                if peer.role == "browser" and peer.participant_id
            )

    async def broadcast(
        self,
        session_id: str,
        message: dict[str, Any],
        *,
        target_role: str,
        participant_id: str = "",
        exclude: RemoteSocket | None = None,
    ) -> int:
        with self._guard:
            targets = [
                peer
                for peer in self._sessions.get(session_id, {}).values()
                if peer is not exclude
                and peer.role == target_role
                and (
                    not participant_id
                    or peer.participant_id == participant_id
                    # Runner 无 participant_id，仍须收齐各路 browser offer/ice。
                    or (not peer.participant_id and peer.role == "runner")
                )
            ]
        sent = 0
        for peer in targets:
            try:
                await peer.websocket.send_json(message)
                sent += 1
            except (RuntimeError, OSError):
                self.disconnect(session_id, peer)
        return sent

    async def broadcast_bytes(
        self,
        session_id: str,
        payload: bytes,
        *,
        target_role: str,
        exclude: RemoteSocket | None = None,
    ) -> int:
        with self._guard:
            targets = [
                peer
                for peer in self._sessions.get(session_id, {}).values()
                if peer is not exclude and peer.role == target_role
            ]
        sent = 0
        for peer in targets:
            try:
                await peer.websocket.send_bytes(payload)
                sent += 1
            except (RuntimeError, OSError, AttributeError):
                self.disconnect(session_id, peer)
        return sent

    def publish(
        self,
        session_id: str,
        message: dict[str, Any],
        *,
        target_role: str,
        participant_id: str = "",
    ) -> bool:
        """供同步 REST service/Runner 线程调用；命中在线 WS 返回 True。"""
        with self._guard:
            loops = {
                peer.loop
                for peer in self._sessions.get(session_id, {}).values()
                if peer.role == target_role
            }
        if not loops:
            return False
        for loop in loops:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(
                    session_id,
                    message,
                    target_role=target_role,
                    participant_id=participant_id,
                ),
                loop,
            )
        return True

    async def close_session(self, session_id: str, code: int = 1000) -> None:
        with self._guard:
            peers = list(self._sessions.pop(session_id, {}).values())
        for peer in peers:
            try:
                await peer.websocket.close(code=code)
            except (RuntimeError, OSError):
                pass


_SOCKET_HUB = DeviceRemoteSocketHub()


def get_remote_socket_hub() -> DeviceRemoteSocketHub:
    return _SOCKET_HUB
