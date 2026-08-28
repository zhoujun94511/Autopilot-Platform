"""Runner 远控 WebSocket 客户端；连接失败时调用方继续使用 HTTP poll。"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

_log = logging.getLogger(__name__)

_SIGNALING_TYPES = frozenset({"offer", "answer", "ice"})
_PEER_CONTROL_TYPES = frozenset({"participant.left", "control.transferred"})


def _ws_url(base_url: str, session_id: str) -> str:
    parts = urlsplit(base_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = f"{parts.path.rstrip('/')}/api/v1/device-remote-sessions/{session_id}/ws"
    query = urlencode({"role": "runner", "connection_id": f"runner-{session_id}"})
    return urlunsplit((scheme, parts.netloc, path, query, ""))


class RunnerRemoteWebSocket:
    def __init__(self, base_url: str, api_token: str, session_id: str) -> None:
        self.url = _ws_url(base_url, session_id)
        self.api_token = api_token
        self.session_id = session_id
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._send_guard = threading.Lock()
        self._pending_binary: bytes | None = None
        self._socket: Any = None
        self._queues: dict[str, queue.Queue[dict[str, Any]]] = {
            "signaling": queue.Queue(maxsize=100),
            "media": queue.Queue(maxsize=30),
            "command": queue.Queue(maxsize=100),
            "event": queue.Queue(maxsize=100),
        }
        self._thread = threading.Thread(
            target=self._run,
            name=f"remote-ws-{session_id[:8]}",
            daemon=True,
        )

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except (OSError, RuntimeError):
                pass
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def send(
        self,
        channel: str,
        name: str,
        payload: dict[str, Any],
        *,
        message_type: str = "event",
        request_id: str = "",
        participant_id: str = "",
        drop_if_busy: bool = False,
    ) -> bool:
        sock = self._socket
        if not self.connected or sock is None:
            return False
        envelope = {
            "channel": channel,
            "type": message_type,
            "name": name,
            "request_id": request_id,
            "participant_id": participant_id,
            "payload": payload,
        }
        try:
            raw = json.dumps(envelope, ensure_ascii=False)
        except (TypeError, ValueError):
            return False
        acquired = self._send_guard.acquire(blocking=not drop_if_busy)
        if not acquired:
            return False
        try:
            sock = self._socket
            if not self.connected or sock is None:
                return False
            sock.send(raw)
            self._drain_pending_binary_locked(sock)
            return True
        except (OSError, RuntimeError, TimeoutError):
            self._connected.clear()
            return False
        finally:
            self._send_guard.release()

    def send_binary(self, payload: bytes, *, drop_if_busy: bool = False) -> bool:
        """发送 APJF 二进制画面。busy 时只保留最新一帧，锁释放后再发出。"""
        sock = self._socket
        if not self.connected or sock is None or not payload:
            return False
        if drop_if_busy:
            acquired = self._send_guard.acquire(blocking=False)
            if not acquired:
                self._pending_binary = payload
                return True
        else:
            self._send_guard.acquire()
        try:
            sock = self._socket
            if not self.connected or sock is None:
                return False
            self._pending_binary = None
            sock.send(payload)
            self._drain_pending_binary_locked(sock)
            return True
        except (OSError, RuntimeError, TimeoutError):
            self._connected.clear()
            self._pending_binary = None
            return False
        finally:
            self._send_guard.release()

    def _drain_pending_binary_locked(self, sock: Any) -> None:
        while True:
            nxt = self._pending_binary
            self._pending_binary = None
            if not nxt:
                return
            sock.send(nxt)

    def drain(self, channel: str) -> list[dict[str, Any]]:
        q = self._queues.get(channel)
        if q is None:
            return []
        out: list[dict[str, Any]] = []
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                return out

    def drain_signaling(self) -> list[dict[str, Any]]:
        """signaling + command + event 里误路由的 SDP 帧（HTTP publish 裸 payload 兜底）。"""
        messages = self.drain("signaling")
        messages.extend(self.drain("command"))
        for item in self.drain("event"):
            kind = str(item.get("type") or item.get("name") or "")
            if kind in _SIGNALING_TYPES or kind in _PEER_CONTROL_TYPES:
                messages.append(item)
        return messages

    def _enqueue(self, channel: str, message: dict[str, Any]) -> None:
        item: dict[str, Any]
        if isinstance(message.get("payload"), dict):
            channel = str(message.get("channel") or channel or "signaling")
            item = dict(message["payload"])
            env_pid = str(message.get("participant_id") or "").strip()
            if env_pid and not str(item.get("participant_id") or "").strip():
                item["participant_id"] = env_pid
            env_name = str(message.get("name") or "").strip()
            if env_name and not str(item.get("type") or "").strip():
                item["type"] = env_name
        else:
            msg_type = str(message.get("type") or "")
            if not channel and msg_type in ("offer", "answer", "ice"):
                channel = "signaling"
            item = dict(message)
        q = self._queues.get(channel, self._queues["event"])
        if q.full():
            try:
                q.get_nowait()
            except queue.Empty:
                pass
        q.put_nowait(item)

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                from websockets.sync.client import connect

                with connect(
                    self.url,
                    additional_headers={"X-API-Token": self.api_token},
                    open_timeout=3,
                    close_timeout=1,
                ) as sock:
                    self._socket = sock
                    self._connected.set()
                    backoff = 0.5
                    while not self._stop.is_set():
                        try:
                            raw = sock.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        if raw is None:
                            break
                        if isinstance(raw, (bytes, bytearray)):
                            continue
                        message = json.loads(raw)
                        if isinstance(message, dict):
                            self._enqueue(str(message.get("channel") or ""), message)
            except Exception as exc:  # noqa: BLE001
                # ConnectionClosedOK 等原先未捕获，WS 线程直接退出，画面改走 HTTP、按键丢失。
                if self._stop.is_set():
                    return
                _log.debug("remote websocket unavailable, HTTP fallback: %s", exc)
            finally:
                self._connected.clear()
                self._socket = None
            if not self._stop.is_set():
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 10.0)
