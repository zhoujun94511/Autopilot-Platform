"""Runner 远控会话中枢：拉取 Platform pending 指令并拉起 Android/iOS 会话。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

from .capacity import max_concurrent_remote
from .prewarm import prewarm_android_scrcpy
from .shared.channels import RemoteChannels

_log = logging.getLogger(__name__)


class RemotePlatformClient(Protocol):
    def list_remote_commands(self, runner_id: str = "") -> list[dict[str, Any]]: ...

    def list_prewarm_hints(self, runner_id: str = "") -> list[dict[str, Any]]: ...

    def post_remote_signaling(
        self, session_id: str, path: str, body: dict[str, Any]
    ) -> None: ...

    def poll_remote_signaling(self, session_id: str) -> dict[str, Any]: ...

    def post_remote_media(self, session_id: str, body: dict[str, Any]) -> None: ...

    def poll_remote_media(self, session_id: str) -> dict[str, Any]: ...

    def post_remote_device_logs(
        self, session_id: str, body: dict[str, Any]
    ) -> None: ...

    def report_remote_status(
        self,
        session_id: str,
        *,
        status: str,
        error_message: str = "",
        capabilities: list[str] | None = None,
    ) -> None: ...


class RemoteSessionHub:
    """按 session_id 管理本机远控会话。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Any] = {}
        self._last_wanted: frozenset[str] = frozenset()

    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def sync(self, client: RemotePlatformClient, *, runner_id: str = "") -> None:
        t0 = time.monotonic()
        try:
            commands = client.list_remote_commands(runner_id) or []
        except Exception as exc:  # noqa: BLE001
            print(f"[runner] remote-commands error: {exc}", flush=True)
            return

        wanted = {str(c.get("session_id") or "") for c in commands}
        wanted.discard("")
        wanted_frozen = frozenset(wanted)
        if wanted_frozen != self._last_wanted:
            print(
                f"[runner] remote-commands n={len(wanted)} "
                f"({time.monotonic() - t0:.2f}s)",
                flush=True,
            )
            self._last_wanted = wanted_frozen

        limit = max_concurrent_remote()
        with self._lock:
            for sid, sess in list(self._sessions.items()):
                if sid not in wanted:
                    try:
                        sess.stop()
                        remote_channels = getattr(sess, "remote_channels", None)
                        if remote_channels is not None:
                            remote_channels.close()
                    except Exception as exc:  # noqa: BLE001
                        _log.debug("stop session %s: %s", sid, exc)
                    self._sessions.pop(sid, None)

            deferred = 0
            for cmd in commands:
                sid = str(cmd.get("session_id") or "")
                if not sid:
                    continue
                existing = self._sessions.get(sid)
                if existing is not None:
                    alive_fn = getattr(existing, "is_alive", None)
                    if callable(alive_fn) and not alive_fn():
                        print(
                            f"[runner] remote respawn dead sid={sid[:12]}",
                            flush=True,
                        )
                        try:
                            existing.stop()
                            remote_channels = getattr(existing, "remote_channels", None)
                            if remote_channels is not None:
                                remote_channels.close()
                        except Exception as exc:  # noqa: BLE001
                            _log.debug("stop dead session %s: %s", sid, exc)
                        self._sessions.pop(sid, None)
                    else:
                        continue
                if len(self._sessions) >= limit:
                    deferred += 1
                    continue
                platform = str(cmd.get("platform") or "").lower()
                udid = str(cmd.get("udid") or "")
                if not udid:
                    continue
                status = str(cmd.get("status") or "")
                if status not in ("pending", "ready", "connected"):
                    continue
                sess = self._spawn(
                    client,
                    sid,
                    udid,
                    platform,
                    ice_servers=list(cmd.get("ice_servers") or []),
                )
                if sess is not None:
                    self._sessions[sid] = sess
                    print(
                        f"[runner] remote spawn sid={sid[:12]} "
                        f"platform={platform} udid={udid[:12]} "
                        f"({len(self._sessions)}/{limit})",
                        flush=True,
                    )
                    if platform == "android":
                        threading.Thread(
                            target=prewarm_android_scrcpy,
                            args=(udid,),
                            name=f"remote-prewarm-{udid[:8]}",
                            daemon=True,
                        ).start()
                    try:
                        sess.start()
                    except Exception as exc:  # noqa: BLE001
                        _log.warning("start remote session failed: %s", exc)
            if deferred:
                print(
                    f"[runner] remote capacity defer n={deferred} "
                    f"(active={len(self._sessions)}/{limit})",
                    flush=True,
                )

    @staticmethod
    def _spawn(
        client: RemotePlatformClient,
        session_id: str,
        udid: str,
        platform: str,
        ice_servers: list[dict[str, Any]] | None = None,
    ) -> Any:
        def report(status: str, error: str = "") -> None:
            try:
                client.report_remote_status(
                    session_id, status=status, error_message=error or ""
                )
            except Exception as exc:  # noqa: BLE001
                _log.debug("report_remote_status: %s", exc)

        channels = RemoteChannels(client, session_id)

        if platform == "android":
            from .android.session import AndroidRemoteSession
            from .android.cold_start_trace import mark

            mark(
                "hub.spawn.android",
                udid=udid,
                session_id=session_id[:12],
            )

            session = AndroidRemoteSession(
                session_id=session_id,
                udid=udid,
                post_signaling=channels.post_signaling,
                poll_signaling=channels.poll_signaling,
                poll_media=channels.poll_media,
                report_status=report,
                post_media=channels.post_media,
                ice_servers=list(ice_servers or []),
            )
            session.remote_channels = channels
            return session

        if platform == "ios":
            from .ios.session import IosRemoteSession

            session = IosRemoteSession(
                session_id=session_id,
                udid=udid,
                post_media=channels.post_media,
                poll_media=channels.poll_media,
                report_status=report,
            )
            session.remote_channels = channels
            return session

        channels.close()
        report("failed", f"unsupported platform: {platform}")
        return None


_HUB: RemoteSessionHub | None = None


def get_hub() -> RemoteSessionHub:
    global _HUB
    if _HUB is None:
        _HUB = RemoteSessionHub()
    return _HUB
