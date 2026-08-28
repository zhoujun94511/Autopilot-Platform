"""iOS 远控：IosDevicePrep + WDA MJPEG 推帧 + WDA 触控。"""

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

    def _handle_stream_command(
        self, event: dict[str, Any]
    ) -> dict[str, Any]:
        command = str(event.get("t") or "")
        if command == "stream.configure":
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

    def stop(self) -> None:
        self._stop.set()
        worker = self._wda_worker
        if (
            worker is not None
            and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(timeout=1.0)
        self._wda_worker = None
        aux = self._aux_worker
        if (
            aux is not None
            and aux.is_alive()
            and aux is not threading.current_thread()
        ):
            aux.join(timeout=1.0)
        self._aux_worker = None
        if self._reader is not None:
            reader = self._reader
            self._reader = None
            # noinspection PyBroadException
            try:
                reader.stop()
            except Exception:  # noqa: BLE001
                pass
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
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

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

    def _run(self) -> None:
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

        mjpeg_url = prep.mjpeg_url()
        connected = False

        def on_frame(jpeg: bytes, w: int, h: int) -> None:
            nonlocal connected
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
                if not connected:
                    connected = True
                    print(
                        f"[runner] remote {self.session_id[:12]} ios first frame",
                        flush=True,
                    )
                    self._report("connected", "")
            except Exception as frame_err:  # noqa: BLE001
                _log.debug("post frame: %s", frame_err)

        def on_unhealthy(reason: str) -> None:
            _log.warning("iOS MJPEG unhealthy: %s", reason)
            self._push_screenshot_fallback(reason)

        self._reader = MjpegReader(
            mjpeg_url,
            on_frame,
            fps=self._fps,
            stop_event=self._stop,
            on_unhealthy=on_unhealthy,
        )
        self._reader.start()
        self._start_wda_worker()

        while not self._stop.is_set():
            if time.monotonic() < self._fallback_until:
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

        self.stop()
