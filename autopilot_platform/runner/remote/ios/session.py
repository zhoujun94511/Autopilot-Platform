"""iOS 远控：IosDevicePrep +（iOS 27 HEVC 或 WDA MJPEG）画面 + WDA 触控。"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

from ..shared.stream_limits import sanitize_ios_stream_config
from .input_dispatch import TouchState, coerce_input_event, dispatch_input
from .mjpeg_reader import MjpegReader
from .quality_controller import IosQualityController

_log = logging.getLogger(__name__)

_REMOTE_WDA_SETTINGS = {
    "mjpegServerFramerate": 12,
    "mjpegServerScreenshotQuality": 45,
    "mjpegScalingFactor": 60,
    "waitForIdleTimeout": 0,
    "animationCoolOffTimeout": 0,
    "shouldUseCompactResponses": True,
}
# 会话/截图等通用 WDA HTTP；Home/音量走 press_button 的 3s，不吃这个值。
_REMOTE_WDA_TIMEOUT = 15.0
# 对齐 Flask：画面线程只 poll/推帧；WDA 按键走独立队列，失败不影响 MJPEG。
_WDA_JOB_QUEUE = 48
_AUX_JOB_QUEUE = 16


def command_job_lane(name: str) -> str:
    """file/app/无障碍走 go-ios，不能堵 Home/触控的 WDA 队列。"""
    text = str(name or "")
    if text.startswith(("file.", "app.")) or text.startswith("accessibility"):
        return "aux"
    return "wda"


class IosRemoteSession:
    def __init__(
        self,
        *,
        session_id: str,
        udid: str,
        post_media: Callable[[dict[str, Any]], None],
        poll_media: Callable[[], list[dict[str, Any]]],
        report_status: Callable[[str, str], None],
        fps: float = 12.0,
    ) -> None:
        self.session_id = session_id
        self.udid = udid
        self._post_media = post_media
        self._poll_media = poll_media
        self._report = report_status
        self._fps = fps
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prep: Any = None
        self._wda: Any = None
        self._reader: MjpegReader | None = None
        self._hevc: Any = None
        self._hevc_pump: threading.Thread | None = None
        self._video_mode = "mjpeg"
        self._hevc_choice = ""
        self._hevc_ws_down = False
        self._mjpeg_url = ""
        self.remote_channels: Any = None
        self._runtime_acquired = False
        self._touch = TouchState()
        self._display_w = 0
        self._display_h = 0
        self._device_w = 0
        self._device_h = 0
        self._fallback_until = 0.0
        self._last_fallback = 0.0
        self._jpeg_quality = 45
        self._mjpeg_scaling = 60
        self._quality = IosQualityController(fps)
        self._quality.enabled = True
        self._wda_jobs: queue.Queue[Callable[[], None]] = queue.Queue(
            maxsize=_WDA_JOB_QUEUE
        )
        self._aux_jobs: queue.Queue[Callable[[], None]] = queue.Queue(
            maxsize=_AUX_JOB_QUEUE
        )
        self._wda_worker: threading.Thread | None = None
        self._aux_worker: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._video_lock = threading.RLock()
        self._closed = False
        self._hevc_linger: list[Any] = []

    def _handle_stream_command(
        self, event: dict[str, Any]
    ) -> dict[str, Any]:
        command = str(event.get("t") or "")
        if command == "stream.configure":
            provider = str(event.get("provider") or "").strip().lower()
            if provider == "mjpeg":
                self._hevc_choice = "mjpeg"
                if self._video_mode == "hevc" or self._hevc is not None:
                    self._fallback_hevc_to_mjpeg("browser")
            elif provider == "hevc" and self._hevc_choice != "mjpeg":
                self._hevc_choice = "hevc"
            cfg = sanitize_ios_stream_config(event)
            if "max_fps" in cfg:
                self._fps = float(cfg["max_fps"])
                self._quality.target_fps = self._fps
                if self._reader is not None:
                    self._reader.set_fps(self._fps)
            if "jpeg_quality" in cfg:
                self._jpeg_quality = cfg["jpeg_quality"]
            if "mjpeg_scaling" in cfg:
                self._mjpeg_scaling = cfg["mjpeg_scaling"]
            if event.get("adaptive") is not None:
                self._quality.enabled = bool(event.get("adaptive"))
            if self._wda is not None:
                try:
                    self._wda.update_settings(
                        {
                            "mjpegServerFramerate": int(self._fps),
                            "mjpegServerScreenshotQuality": self._jpeg_quality,
                            "mjpegScalingFactor": int(self._mjpeg_scaling),
                        }
                    )
                except Exception as err:  # noqa: BLE001
                    _log.debug("dynamic WDA MJPEG settings: %s", err)
        elif command == "stream.keyframe":
            hevc = self._hevc
            if self._video_mode == "hevc" and hevc is not None:
                hevc.request_keyframe()
            else:
                self._push_screenshot_fallback("manual-keyframe")
        snapshot = self._quality.snapshot()
        return {
            "ok": True,
            "config": {
                "max_fps": self._fps,
                "jpeg_quality": self._jpeg_quality,
                "mjpeg_scaling": self._mjpeg_scaling,
                "adaptive": self._quality.enabled,
            },
            "stats": {
                "average_frame_bytes": snapshot.average_frame_bytes,
                "average_interval_ms": snapshot.average_interval_ms,
                "regime": snapshot.regime,
            },
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"remote-ios-{self.udid[:8]}", daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _start_wda_worker(self) -> None:
        if self._wda_worker is None or not self._wda_worker.is_alive():
            self._wda_worker = threading.Thread(
                target=self._wda_worker_loop,
                name=f"remote-ios-ctrl-{self.udid[:8]}",
                daemon=True,
            )
            self._wda_worker.start()
        if self._aux_worker is None or not self._aux_worker.is_alive():
            self._aux_worker = threading.Thread(
                target=self._aux_worker_loop,
                name=f"remote-ios-aux-{self.udid[:8]}",
                daemon=True,
            )
            self._aux_worker.start()

    def _wda_worker_loop(self) -> None:
        self._job_loop(self._wda_jobs, "ios wda control")

    def _aux_worker_loop(self) -> None:
        self._job_loop(self._aux_jobs, "ios aux command")

    def _job_loop(
        self,
        jobs: queue.Queue[Callable[[], None]],
        label: str,
    ) -> None:
        while not self._stop.is_set():
            try:
                job = jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                job()
            except Exception as exc:  # noqa: BLE001
                _log.warning("%s: %s", label, exc)

    @staticmethod
    def _submit_job(
            jobs: queue.Queue[Callable[[], None]],
        job: Callable[[], None],
        *,
        drop_label: str,
    ) -> None:
        if jobs.full():
            try:
                jobs.get_nowait()
            except queue.Empty:
                pass
        try:
            jobs.put_nowait(job)
        except queue.Full:
            _log.warning("%s queue full, drop", drop_label)

    def _submit_wda(self, job: Callable[[], None]) -> None:
        """Flask 的 POST /button 不堵 MJPEG；这里用队列等价拆开。"""
        self._submit_job(self._wda_jobs, job, drop_label="ios wda control")

    def _submit_aux(self, job: Callable[[], None]) -> None:
        self._submit_job(self._aux_jobs, job, drop_label="ios aux command")

    @staticmethod
    def _join_thread(thread: threading.Thread | None, timeout: float) -> None:
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=timeout)

    def stop(self) -> None:
        self._stop.set()
        self._join_thread(self._wda_worker, 1.0)
        self._wda_worker = None
        self._join_thread(self._aux_worker, 1.0)
        self._aux_worker = None
        with self._lifecycle_lock:
            if not self._closed:
                self._closed = True
                with self._video_lock:
                    self._stop_hevc()
                    self._reap_lingering_hevc()
                    reader = self._reader
                    self._reader = None
                if reader is not None:
                    # noinspection PyBroadException
                    try:
                        reader.stop()
                    except Exception:  # noqa: BLE001
                        pass
                self._release_session_resources()
        self._join_thread(self._thread, 2.0)
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None or not thread.is_alive() or thread is threading.current_thread():
                self._thread = None

    def _release_session_resources(self) -> None:
        """WDA、prep、设备 runtime。只从第一次 stop() 的锁内调用。"""
        if self._wda is not None:
            wda = self._wda
            self._wda = None
            # noinspection PyBroadException
            try:
                wda.delete_session()
            except Exception:  # noqa: BLE001
                pass
            # noinspection PyBroadException
            try:
                http = getattr(wda, "_http", None)
                if http is not None:
                    http.close()
            except Exception:  # noqa: BLE001
                pass
        if self._prep is not None:
            prep = self._prep
            self._prep = None
            # noinspection PyBroadException
            try:
                prep.stop()
            except Exception:  # noqa: BLE001
                pass
        # noinspection PyBroadException
        try:
            from .app_ops import cleanup_pending_installs

            cleanup_pending_installs()
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..shared.device_log_pump import stop as stop_device_log

            stop_device_log(self.session_id)
        except (ImportError, OSError, RuntimeError):
            pass
        if self._runtime_acquired:
            self._runtime_acquired = False
            # noinspection PyBroadException
            try:
                from autopilot_platform.ap.runtime.device_runtime import (
                    release_device_runtime,
                )

                release_device_runtime(self.udid)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _apply_wda_settings(wda: Any) -> None:
        try:
            wda.update_settings(dict(_REMOTE_WDA_SETTINGS))
        except Exception as err:  # noqa: BLE001
            _log.debug("wda update_settings: %s", err)

    def _wire_recover(self, wda: Any) -> None:
        def _recover() -> None:
            _log.warning("iOS remote WDA session lost; recreating")
            try:
                wda.recreate_session()
                self._apply_wda_settings(wda)
            except Exception as recover_err:  # noqa: BLE001
                _log.warning("wda recreate failed: %s", recover_err)
                raise

        try:
            wda.set_recover(_recover)
        except Exception as err:  # noqa: BLE001
            _log.debug("set_recover: %s", err)

    def _push_screenshot_fallback(self, reason: str) -> None:
        if self._stop.is_set() or self._wda is None:
            return
        now = time.monotonic()
        if now - self._last_fallback < 1.0:
            return
        self._last_fallback = now
        self._fallback_until = now + 8.0
        try:
            png = self._wda.screenshot_png()
        except Exception as exc:  # noqa: BLE001
            _log.warning("screenshot fallback failed (%s): %s", reason, exc)
            return
        if not png:
            return
        try:
            self._post_media(
                {
                    "type": "frame",
                    "from_role": "runner",
                    "jpeg": png,
                    "width": self._device_w or self._display_w,
                    "height": self._device_h or self._display_h,
                    "mime": "image/png",
                }
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("post fallback frame: %s", exc)

    def _want_hevc(self) -> bool:
        from autopilot_platform.ap.mobile.ios_bootstrap import device_ios_version
        from .hevc_stream import (
            hevc_api_available,
            hevc_enabled_by_env,
            hevc_supported_ios,
        )

        if not hevc_enabled_by_env() or not hevc_api_available():
            return False
        return hevc_supported_ios(device_ios_version(self.udid))

    def _mark_connected(self, connected: list[bool]) -> None:
        if connected[0]:
            return
        connected[0] = True
        print(
            f"[runner] remote {self.session_id[:12]} ios first frame",
            flush=True,
        )
        self._report("connected", "")

    def _post_jpeg_frame(self, jpeg: bytes, w: int, h: int, connected: list[bool]) -> None:
        if self._stop.is_set():
            return
        if w > 0:
            self._display_w = w
        if h > 0:
            self._display_h = h
        adaptive_fps = self._quality.observe(len(jpeg))
        if adaptive_fps is not None and self._reader is not None:
            self._fps = adaptive_fps
            self._reader.set_fps(adaptive_fps)
        try:
            self._post_media(
                {
                    "type": "frame",
                    "from_role": "runner",
                    "jpeg": jpeg,
                    "width": self._display_w,
                    "height": self._display_h,
                    "mime": "image/jpeg",
                }
            )
            self._mark_connected(connected)
        except Exception as frame_err:  # noqa: BLE001
            _log.debug("post frame: %s", frame_err)

    def _start_mjpeg(self, connected: list[bool]) -> None:
        with self._video_lock:
            if self._reader is not None or self._stop.is_set():
                return
            url = self._mjpeg_url
            if not url:
                return

            def on_frame(jpeg: bytes, w: int, h: int) -> None:
                self._post_jpeg_frame(jpeg, w, h, connected)

            def on_unhealthy(reason: str) -> None:
                _log.warning("iOS MJPEG unhealthy: %s", reason)
                self._push_screenshot_fallback(reason)

            self._video_mode = "mjpeg"
            self._reader = MjpegReader(
                url,
                on_frame,
                fps=self._fps,
                stop_event=self._stop,
                on_unhealthy=on_unhealthy,
            )
            self._reader.start()

    def _remember_hevc(self, hevc: Any) -> None:
        alive = getattr(hevc, "thread_alive", None)
        if callable(alive) and alive():
            _log.warning("iOS HEVC 线程在停止后仍存活，保留引用以便再次 join")
            self._hevc_linger.append(hevc)

    def _reap_lingering_hevc(self) -> None:
        still: list[Any] = []
        for hevc in self._hevc_linger:
            # noinspection PyBroadException
            try:
                hevc.stop()
            except Exception:  # noqa: BLE001
                _log.debug("hevc reap", exc_info=True)
            alive = getattr(hevc, "thread_alive", None)
            if callable(alive) and alive():
                still.append(hevc)
        self._hevc_linger = still

    def _stop_hevc(self) -> None:
        self._video_mode = "mjpeg"
        hevc = self._hevc
        self._hevc = None
        if hevc is not None:
            # noinspection PyBroadException
            try:
                hevc.stop()
            except Exception:  # noqa: BLE001
                _log.debug("hevc stop", exc_info=True)
            self._remember_hevc(hevc)
        pump = self._hevc_pump
        self._hevc_pump = None
        if pump is not None and pump.is_alive() and pump is not threading.current_thread():
            pump.join(timeout=2.0)

    def _fallback_hevc_to_mjpeg(self, reason: str) -> None:
        with self._video_lock:
            if self._video_mode != "hevc" and self._hevc is None:
                return
            _log.warning("iOS HEVC 回退 MJPEG: %s", reason)
            self._stop_hevc()
            if not self._stop.is_set():
                self._start_mjpeg([False])

    def _pump_hevc(self, connected: list[bool]) -> None:
        from .hevc_stream import HevcAccessUnit
        from autopilot_platform.runner.remote.shared.frame_bus import (
            pack_hevc_au,
            pack_hevc_config,
        )

        sent_config = False
        send_fails = 0
        hevc = self._hevc
        while (
            not self._stop.is_set()
            and not self._hevc_ws_down
            and self._video_mode == "hevc"
            and hevc is not None
        ):
            channels = self.remote_channels
            if channels is not None and getattr(channels, "hevc_needs_key", False):
                channels.hevc_needs_key = False
                hevc.request_keyframe()
            unit = hevc.read(0.5)
            if not isinstance(unit, HevcAccessUnit):
                continue
            # noinspection PyBroadException
            try:
                if unit.keyframe and unit.codec_string and unit.description:
                    posted = self._post_media(
                        {
                            "type": "hevc",
                            "packet": pack_hevc_config(unit.codec_string, unit.description),
                        }
                    )
                    if not posted:
                        send_fails += 1
                        if send_fails >= 3:
                            self._hevc_ws_down = True
                        continue
                    sent_config = True
                elif not sent_config:
                    continue
                posted_au = self._post_media(
                    {"type": "hevc", "packet": pack_hevc_au(unit.webcodecs_packet())}
                )
                if posted_au:
                    send_fails = 0
                    if unit.keyframe:
                        self._mark_connected(connected)
                elif unit.keyframe:
                    send_fails += 1
                    if send_fails >= 3:
                        self._hevc_ws_down = True
            except Exception as exc:  # noqa: BLE001
                _log.debug("post hevc: %s", exc)

    def _try_start_hevc(self, connected: list[bool]) -> bool:
        from .hevc_stream import IosHevcStream

        stream = IosHevcStream(self.udid)
        # 先挂上，stop()/浏览器拒绝才能在 start() 阻塞期间关掉隧道。
        self._hevc = stream
        self._video_mode = "hevc"
        # noinspection PyBroadException
        try:
            stream.start()
        except Exception as exc:  # noqa: BLE001
            _log.warning("iOS HEVC 未启动，改走 MJPEG: %s", exc)
            if self._hevc is stream:
                self._stop_hevc()
            else:
                # noinspection PyBroadException
                try:
                    stream.stop()
                except Exception:  # noqa: BLE001
                    pass
            return False
        if self._stop.is_set() or self._hevc is not stream or self._video_mode != "hevc":
            if self._hevc is stream:
                self._stop_hevc()
            return False
        pump = threading.Thread(
            target=self._pump_hevc,
            args=(connected,),
            name=f"remote-ios-hevc-{self.udid[:8]}",
            daemon=True,
        )
        self._hevc_pump = pump
        pump.start()
        print(
            f"[runner] remote {self.session_id[:12]} ios hevc",
            flush=True,
        )
        return True

    def _run(self) -> None:
        try:
            self._run_session()
        finally:
            self.stop()

    def _run_session(self) -> None:
        print(
            f"[runner] remote {self.session_id[:12]} ios starting "
            f"udid={self.udid[:12]}",
            flush=True,
        )
        try:
            from autopilot_platform.ap.keywords.mobile.wda_client import WdaClient
            from autopilot_platform.ap.mobile.ios_bootstrap import (
                IosDevicePrep,
                ensure_mjpeg_ready,
                mjpeg_alive,
            )
            from autopilot_platform.ap.runtime.device_runtime import (
                acquire_device_runtime,
            )
            from ..shared.command_protocol import normalize_reliable_command
            from .command_dispatch import dispatch as dispatch_command
        except Exception as exc:  # noqa: BLE001
            self._report("failed", f"import error: {exc}")
            return

        def _prep_log(message: str) -> None:
            print(
                f"[runner] remote {self.session_id[:12]} ios {message}",
                flush=True,
            )

        try:
            t_prep = time.monotonic()
            runtime = acquire_device_runtime(self.udid, "ios")
            self._runtime_acquired = True
            ports = runtime.ports
            _prep_log(
                f"prep begin tunnel={ports.tunnel_port} "
                f"wda={ports.wda_port} mjpeg={ports.mjpeg_port}"
            )
            prep = IosDevicePrep(
                self.udid,
                "",
                info_port=ports.tunnel_port,
                wda_port=ports.wda_port,
                mjpeg_port=ports.mjpeg_port,
                log=_prep_log,
                cancel_event=self._stop,
            )
            self._prep = prep
            wda_url = prep.prepare()
            if not ensure_mjpeg_ready(
                self.udid,
                mjpeg_port=ports.mjpeg_port,
                prep=prep,
                timeout=20.0,
            ):
                if not mjpeg_alive(ports.mjpeg_port):
                    self._report("failed", f"MJPEG {ports.mjpeg_port} 未就绪")
                    self.stop()
                    return
            wda = WdaClient(
                wda_url or f"http://127.0.0.1:{ports.wda_port}",
                timeout=_REMOTE_WDA_TIMEOUT,
            )
            wda.create_session()
            self._apply_wda_settings(wda)
            self._wire_recover(wda)
            self._wda = wda
            # noinspection PyBroadException
            try:
                size = wda.window_size() or {}
                self._device_w = int(size.get("width") or 0)
                self._device_h = int(size.get("height") or 0)
            except Exception:  # noqa: BLE001
                pass
            print(
                f"[runner] remote {self.session_id[:12]} ios wda ready "
                f"({time.monotonic() - t_prep:.2f}s)",
                flush=True,
            )
            self._report("ready", "")
        except Exception as prep_err:  # noqa: BLE001
            _log.exception("iOS remote prep failed")
            self._report("failed", f"ios prep: {prep_err}")
            self.stop()
            return

        self._mjpeg_url = prep.mjpeg_url()
        connected = [False]
        self._start_wda_worker()
        # 先让浏览器声明 hevc / mjpeg，再开 startmediastream，避免解不了也锁相机。
        prefer_hevc = self._want_hevc()
        choice_deadline = time.monotonic() + (3.0 if prefer_hevc else 0.0)
        picture_started = False

        while not self._stop.is_set():
            if not picture_started and (
                self._hevc_choice
                or not prefer_hevc
                or time.monotonic() >= choice_deadline
            ):
                picture_started = True
                opened = (
                    self._hevc_choice != "mjpeg"
                    and prefer_hevc
                    and self._try_start_hevc(connected)
                )
                if not opened and not self._stop.is_set():
                    self._start_mjpeg(connected)
            hevc = self._hevc
            if self._hevc_ws_down or (
                self._video_mode == "hevc"
                and hevc is not None
                and not hevc.health()
            ):
                self._hevc_ws_down = False
                self._fallback_hevc_to_mjpeg("unhealthy")
            if self._video_mode != "hevc" and time.monotonic() < self._fallback_until:
                self._push_screenshot_fallback("poll-fallback")
            try:
                msgs = self._poll_media() or []
            except Exception as exc:  # noqa: BLE001
                _log.warning("media poll failed: %s", exc)
                msgs = []
            for msg in msgs:
                message_type = str(msg.get("type") or msg.get("name") or "")
                command_event = normalize_reliable_command(msg)
                payload = (
                    command_event
                    if command_event is not None
                    else msg.get("payload")
                    if isinstance(msg.get("payload"), dict)
                    else None
                )
                if payload is None and isinstance(msg.get("t"), str):
                    payload = msg
                if payload is None or not isinstance(payload, dict):
                    continue

                def reply(result: dict[str, Any]) -> None:
                    self._post_media(
                        {
                            "type": "command_reply",
                            "from_role": "runner",
                            "payload": result,
                        }
                    )

                if command_event is not None:
                    command_name = str(command_event.get("t") or "")
                    if command_name.startswith("log."):
                        from ..shared.device_log_pump import (
                            handle_command as handle_log,
                        )

                        def _post_device_logs(lines: list[str]) -> None:
                            channels = getattr(self, "remote_channels", None)
                            if channels is not None:
                                channels.post_device_logs(lines)

                        handle_log(
                            session_id=self.session_id,
                            udid=self.udid,
                            platform="ios",
                            event=command_event,
                            post_lines=_post_device_logs,
                            reply=reply,
                        )
                        continue
                    command_body = command_event

                    def _make_cmd_job(
                        body: dict[str, Any],
                        respond: Callable[[dict[str, Any]], None],
                    ) -> Callable[[], None]:
                        def _cmd_job() -> None:
                            try:
                                dispatch_command(
                                    self._wda,
                                    self.udid,
                                    body,
                                    respond,
                                    stream_handler=self._handle_stream_command,
                                )
                            except Exception as cmd_err:  # noqa: BLE001
                                _log.warning("ios command: %s", cmd_err)

                        return _cmd_job

                    job = _make_cmd_job(command_body, reply)
                    if command_name in (
                        "home",
                        "volumeup",
                        "volumedown",
                        "press_button",
                    ):
                        print(
                            f"[runner] remote {self.session_id[:12]} ios cmd "
                            f"{command_name}",
                            flush=True,
                        )
                    if command_job_lane(command_name) == "aux":
                        self._submit_aux(job)
                    else:
                        self._submit_wda(job)
                    continue
                input_event = coerce_input_event(msg)
                if input_event is None and message_type == "input":
                    input_event = payload
                if input_event is None:
                    continue
                dw = self._display_w or self._device_w or 1
                dh = self._display_h or self._device_h or 1
                box_w = float(dw)
                box_h = float(dh)

                def _make_input_job(
                    input_body: dict[str, Any],
                    width: float,
                    height: float,
                    respond: Callable[[dict[str, Any]], None],
                ) -> Callable[[], None]:
                    def _input_job() -> None:
                        try:
                            dispatch_input(
                                self._wda,
                                input_body,
                                touch_state=self._touch,
                                display_w=width,
                                display_h=height,
                                device_w=float(self._device_w or width),
                                device_h=float(self._device_h or height),
                                reply=respond,
                            )
                        except Exception as input_err:  # noqa: BLE001
                            _log.warning("ios input: %s", input_err)

                    return _input_job

                self._submit_wda(
                    _make_input_job(input_event, box_w, box_h, reply)
                )
            self._stop.wait(0.04)
