"""Android 远控会话：scrcpy + WebRTC，经 Platform HTTP 信令中继。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)


class AndroidRemoteSession:
    """一对一浏览器远控（sid = session_id）。"""

    def __init__(
        self,
        *,
        session_id: str,
        udid: str,
        post_signaling: Callable[[str, dict[str, Any]], None],
        poll_signaling: Callable[[], list[dict[str, Any]]],
        poll_media: Callable[[], list[dict[str, Any]]] | None = None,
        report_status: Callable[[str, str], None],
        post_media: Callable[[dict[str, Any]], None] | None = None,
        ice_servers: list[dict[str, Any]] | None = None,
    ) -> None:
        self.session_id = session_id
        self.udid = udid
        self._post = post_signaling
        self._poll = poll_signaling
        self._poll_media = poll_media
        self._post_media = post_media
        self._report = report_status
        self._ice_servers = list(ice_servers or [])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._active_peer_sid: str | None = None
        self.remote_channels: Any = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"remote-android-{self.udid[:8]}", daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        self._client = None
        try:
            from . import scrcpyclients

            scrcpyclients.stop_client(self.udid)
        except Exception as err:  # noqa: BLE001
            _log.debug("stop_client: %s", err)
        try:
            from .webrtc.peer_manager import get_peer_manager

            get_peer_manager().close_device(self.udid)
        except Exception as err:  # noqa: BLE001
            _log.debug("peer close: %s", err)
        try:
            from .file_transfer import cleanup_all_transfers

            cleanup_all_transfers()
        except Exception as err:  # noqa: BLE001
            _log.debug("file_transfer cleanup: %s", err)
        try:
            from .adb_executor import shutdown_device

            shutdown_device(self.udid, wait=False)
        except Exception as err:  # noqa: BLE001
            _log.debug("adb_executor shutdown: %s", err)
        try:
            from ..shared.device_log_pump import stop as stop_device_log

            stop_device_log(self.session_id)
        except Exception as err:  # noqa: BLE001
            _log.debug("device log stop: %s", err)
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        from .cold_start_trace import ColdStartTrace, set_active

        trace = ColdStartTrace(self.session_id, self.udid)
        set_active(trace)
        trace.mark("session.thread.start")
        try:
            self._run_session(trace)
        finally:
            set_active(None)

    def _run_session(self, trace: Any) -> None:
        from .cold_start_trace import mark

        try:
            from ..shared.command_protocol import normalize_reliable_command
            from . import scrcpyclients
            from .adb_dispatch import dispatch as dispatch_adb
            from .input_dispatch import dispatch
            from .webrtc.peer_manager import get_peer_manager
        except Exception as err:  # noqa: BLE001
            self._report("failed", f"import error: {err}")
            return
        trace.mark("session.imports.ok")

        try:
            mark("scrcpy.get_client.begin")
            client = scrcpyclients.get_client(self.udid)
            if client is None or not getattr(client, "alive", False):
                self._report("failed", "scrcpy client unavailable")
                trace.mark("scrcpy.get_client.failed")
                return
            self._client = client
            res = getattr(client, "resolution", None)
            trace.mark(
                "scrcpy.get_client.ok",
                control_available=getattr(client, "control_available", False),
                resolution=f"{res[0]}x{res[1]}" if res else "unknown",
            )
            self._report("ready", "")
            trace.mark("session.report.ready")
        except Exception as err:  # noqa: BLE001
            trace.mark("scrcpy.get_client.error", error=str(err)[:120])
            self._report("failed", f"scrcpy start: {err}")
            return

        pm = get_peer_manager()
        connected = False
        last_wait_key = ""

        def _maybe_report_connected(active_client: Any, peer: Any) -> None:
            nonlocal connected, last_wait_key
            if connected or self._stop.is_set():
                return
            control_ok = bool(getattr(active_client, "control_available", False))
            input_ok = peer is not None and peer.input_channel_ready()
            pc_state = str(
                getattr(getattr(peer, "pc", None), "connectionState", "") or ""
            )
            if not control_ok or not input_ok:
                wait_key = f"{control_ok}:{input_ok}:{pc_state}"
                if wait_key != last_wait_key:
                    last_wait_key = wait_key
                    mark(
                        "session.wait_control",
                        control_available=control_ok,
                        input_dc_open=input_ok,
                        pc_state=pc_state or "-",
                    )
                return
            connected = True
            client_resolution = getattr(active_client, "resolution", None)
            trace.summary(
                "connected",
                control_available=True,
                input_dc_open=True,
                resolution=(
                    f"{client_resolution[0]}x{client_resolution[1]}"
                    if client_resolution
                    else "unknown"
                ),
            )
            self._report("connected", "")

        def _post_device_logs(lines: list[str]) -> None:
            channels = getattr(self, "remote_channels", None)
            if channels is None:
                return
            channels.post_device_logs(lines)

        def _dispatch_adb_command(envelope: dict[str, Any]) -> bool:
            event = normalize_reliable_command(envelope)
            if event is None:
                return False
            event_type = str(event.get("t") or "")

            def command_reply(reply_body: dict[str, Any]) -> None:
                if self._post_media is not None:
                    self._post_media(
                        {
                            "type": "command_reply",
                            "from_role": "runner",
                            "payload": reply_body,
                        }
                    )

            if event_type.startswith("log."):
                from ..shared.device_log_pump import handle_command as handle_log

                return handle_log(
                    session_id=self.session_id,
                    udid=self.udid,
                    platform="android",
                    event=event,
                    post_lines=_post_device_logs,
                    reply=command_reply,
                )

            message_json = json.dumps(event, ensure_ascii=False)

            def work() -> None:
                dispatch_adb(
                    client,
                    message_json,
                    command_reply,
                    device_id=self.udid,
                )

            from .adb_executor import submit_adb_dispatch

            submit_adb_dispatch(
                self.udid,
                event_type=event_type,
                work=work,
            )
            return True

        def _reply_adb(payload: dict[str, Any], active_peer_sid: str) -> None:
            live = pm.get(active_peer_sid, self.udid)
            if live is not None and live.send_adb(payload):
                return
            if self._post_media is not None:
                self._post_media(
                    {
                        "type": "command_reply",
                        "from_role": "runner",
                        "payload": payload,
                    }
                )

        def _dispatch_input_payload(payload: Any) -> None:
            if payload is None:
                return
            if isinstance(payload, dict) and isinstance(payload.get("batch"), list):
                for item in payload["batch"]:
                    if isinstance(item, dict):
                        _dispatch_input_payload(item)
                return
            if isinstance(payload, dict):
                raw = json.dumps(payload, ensure_ascii=False)
            elif isinstance(payload, (str, bytes)):
                raw = payload.decode("utf-8", "ignore") if isinstance(payload, bytes) else payload
            else:
                return

            def _reply_media_input(reply_payload: dict[str, Any]) -> None:
                active_peer_key = self._active_peer_sid or self.session_id
                peer = pm.get(active_peer_key, self.udid)
                if peer is not None and peer.send_input(reply_payload):
                    return
                if self._post_media is not None:
                    self._post_media(
                        {
                            "type": "command_reply",
                            "from_role": "runner",
                            "payload": reply_payload,
                        }
                    )

            dispatch(
                client,
                raw,
                reply=_reply_media_input,
                device_id=self.udid,
            )

        while not self._stop.is_set():
            try:
                msgs = self._poll() or []
            except Exception as err:  # noqa: BLE001
                _log.warning("signaling poll failed: %s", err)
                msgs = []

            media_msgs: list[dict[str, Any]] = []
            if self._poll_media is not None:
                try:
                    media_msgs = self._poll_media() or []
                except Exception as err:  # noqa: BLE001
                    _log.warning("media poll failed: %s", err)

            for msg in media_msgs:
                message_type = str(msg.get("type") or msg.get("name") or "")
                if _dispatch_adb_command(msg):
                    continue
                inner = msg.get("payload")
                if message_type != "input":
                    continue
                if inner is None and isinstance(msg.get("t"), str):
                    inner = msg
                _dispatch_input_payload(inner)

            for msg in msgs:
                mtype = str(msg.get("type") or "")
                participant_id = str(msg.get("participant_id") or "")
                readonly_peer = str(msg.get("participant_role") or "").strip().lower() == "viewer"
                peer_sid = (
                    f"{self.session_id}:{participant_id}"
                    if participant_id
                    else self.session_id
                )
                if _dispatch_adb_command(msg):
                    continue
                if mtype == "participant.left":
                    try:
                        pm.close(peer_sid, self.udid)
                    except Exception as close_err:  # noqa: BLE001
                        _log.debug("peer left close: %s", close_err)
                    if self._active_peer_sid == peer_sid:
                        self._active_peer_sid = None
                    continue
                if mtype == "offer":
                    sdp = str(msg.get("sdp") or "")
                    if not sdp:
                        continue
                    try:
                        self._active_peer_sid = peer_sid
                        mark(
                            "webrtc.offer.received",
                            participant_id=participant_id or "-",
                            sdp_bytes=len(sdp),
                        )

                        def _emit_ice(ice_cand: dict[str, Any]) -> None:
                            self._post(
                                "ice",
                                {
                                    "type": "ice",
                                    "from_role": "runner",
                                    "candidate": ice_cand,
                                    "sdp": "",
                                    "participant_id": participant_id,
                                },
                            )

                        def _reply_dc_input(payload: dict[str, Any]) -> None:
                            live = pm.get(peer_sid, self.udid)
                            if live is not None:
                                live.send_input(payload)

                        def _on_input(raw: str) -> None:
                            dispatch(
                                client,
                                raw,
                                reply=_reply_dc_input,
                                device_id=self.udid,
                            )

                        def _reply_adb_dc(payload: dict[str, Any]) -> None:
                            _reply_adb(payload, peer_sid)

                        def _on_adb(raw: str | bytes) -> None:
                            event_type = ""
                            parsed: dict[str, Any] | None = None
                            try:
                                loaded = json.loads(
                                    raw
                                    if isinstance(raw, str)
                                    else raw.decode("utf-8", "ignore")
                                )
                                if isinstance(loaded, dict):
                                    parsed = loaded
                                    event_type = str(loaded.get("t") or "")
                            except (TypeError, ValueError, UnicodeDecodeError):
                                pass

                            if parsed is not None and event_type.startswith("log."):
                                from ..shared.device_log_pump import (
                                    handle_command as handle_log,
                                )

                                handle_log(
                                    session_id=self.session_id,
                                    udid=self.udid,
                                    platform="android",
                                    event=parsed,
                                    post_lines=_post_device_logs,
                                    reply=_reply_adb_dc,
                                )
                                return

                            def work() -> None:
                                dispatch_adb(
                                    client,
                                    raw,
                                    _reply_adb_dc,
                                    device_id=self.udid,
                                )

                            from .adb_executor import submit_adb_dispatch

                            submit_adb_dispatch(
                                self.udid,
                                event_type=event_type,
                                work=work,
                            )

                        def _on_closed(state: str) -> None:
                            _log.info(
                                "peer closed session=%s state=%s",
                                self.session_id,
                                state,
                            )
                            # disconnected 常为瞬态 ICE 波动，不拆 PC（见 webrtc_session.py）。
                            if state == "disconnected":
                                return
                            try:
                                pm.detach_video(peer_sid, self.udid)
                            except Exception as detach_err:  # noqa: BLE001
                                _log.debug("detach_video: %s", detach_err)
                            if state in ("failed", "closed"):
                                try:
                                    pm.close(peer_sid, self.udid)
                                except Exception as peer_close_err:  # noqa: BLE001
                                    _log.debug("peer close: %s", peer_close_err)

                        def _on_input_open() -> None:
                            mark("webrtc.input_dc.open")
                            live = pm.get(peer_sid, self.udid)
                            _maybe_report_connected(client, live)

                        # ICE 须在 handle_offer 前挂上（协商期会立刻产生 candidate）。
                        pre = pm.get_or_create(
                            peer_sid,
                            self.udid,
                            ice_servers=self._ice_servers,
                        )
                        pre.on_local_ice(_emit_ice)
                        mark("webrtc.handle_offer.begin")
                        t_offer = time.monotonic()
                        answer = pm.handle_offer(
                            peer_sid, self.udid, sdp, readonly=readonly_peer
                        )
                        mark(
                            "webrtc.handle_offer.ok",
                            elapsed_ms=int((time.monotonic() - t_offer) * 1000),
                        )
                        session = pm.get(peer_sid, self.udid)
                        if session is None:
                            continue
                        # handle_offer 重协商会换新 PeerSession；input/adb 必须在 answer 之后挂到新 PC。
                        # 旁观 peer 不挂控制通道，只读命令走 Platform WS/HTTP。
                        if not readonly_peer:
                            session.on_input_message(_on_input)
                            session.on_adb_message(_on_adb)
                            session.on_input_open(_on_input_open)
                        session.on_closed(_on_closed)
                        session.on_local_ice(_emit_ice)
                        if answer:
                            self._post(
                                "answer",
                                {
                                    "type": "answer",
                                    "from_role": "runner",
                                    "sdp": answer.get("sdp")
                                    if isinstance(answer, dict)
                                    else str(answer),
                                    "candidate": {},
                                    "participant_id": participant_id,
                                },
                            )
                            mark("webrtc.answer.posted")
                            pm.attach_video(
                                peer_sid, self.udid, client
                            )
                            mark(
                                "webrtc.attach_video.ok",
                                control_available=getattr(client, "control_available", False),
                                input_dc_open=session.input_channel_ready(),
                            )
                            _maybe_report_connected(client, session)
                    except TimeoutError:
                        _log.warning(
                            "offer handle timeout session=%s (awaiting client resend)",
                            self.session_id,
                        )
                        continue
                    except Exception as offer_err:  # noqa: BLE001
                        _log.exception("offer handle failed")
                        self._report("failed", f"webrtc: {offer_err}")
                        continue
                elif mtype == "ice":
                    ice_payload = msg.get("candidate") or {}
                    try:
                        pm.handle_ice(peer_sid, self.udid, ice_payload)
                    except Exception as ice_err:  # noqa: BLE001
                        _log.debug("ice handle: %s", ice_err)

            if not connected and client is not None:
                peer_key = self._active_peer_sid or self.session_id
                live_peer = pm.get(peer_key, self.udid)
                _maybe_report_connected(client, live_peer)

            self._stop.wait(0.2)

        # noinspection PyBroadException
        try:
            pm.close_device(self.udid)
        except Exception:  # noqa: BLE001
            pass
        # noinspection PyBroadException
        try:
            scrcpyclients.stop_client(self.udid)
        except Exception:  # noqa: BLE001
            pass
