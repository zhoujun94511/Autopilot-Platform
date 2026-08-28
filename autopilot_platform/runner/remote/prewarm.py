"""占用后 soft prewarm + adb 守护进程预热。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)

_adb_guard = threading.Lock()
_adb_warmed = False
_recent_guard = threading.Lock()
_recent_soft: dict[str, float] = {}
SOFT_PREWARM_TTL_SEC = 120.0

_webrtc_warmed = False
_webrtc_warm_lock = threading.Lock()


def ensure_adb_daemon() -> bool:
    """先暖 adb daemon，再并行扫设备/建连（ws-scrcpy-web 同款策略）。"""
    global _adb_warmed
    with _adb_guard:
        if _adb_warmed:
            return True
        try:
            # noinspection PyPackageRequirements
            from adbutils import adb  # type: ignore[import-untyped]

            adb.server_version()
            _adb_warmed = True
            print("[runner] adb daemon ready", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001
            _log.debug("adb prewarm: %s", exc)
            return False


def _recently_soft_prewarmed(udid: str) -> bool:
    uid = (udid or "").strip()
    if not uid:
        return True
    now = time.monotonic()
    with _recent_guard:
        ts = _recent_soft.get(uid)
        if ts is not None and now - ts < SOFT_PREWARM_TTL_SEC:
            return True
        _recent_soft[uid] = now
        stale = [k for k, v in _recent_soft.items() if now - v > SOFT_PREWARM_TTL_SEC * 2]
        for k in stale:
            _recent_soft.pop(k, None)
    return False


def soft_prewarm_android(udid: str) -> None:
    """占用后轻量预热：adb + jar 就绪检查；不强制 full scrcpy（留给开远控）。"""
    if _recently_soft_prewarmed(udid):
        return
    ensure_adb_daemon()
    try:
        from .android import scrcpyclients

        if scrcpyclients.peek_client(udid) is not None:
            print(
                f"[runner] soft-prewarm android skip udid={udid[:12]} (client alive)",
                flush=True,
            )
            return
        if scrcpyclients.remote_jar_matches_local(udid):
            print(
                f"[runner] soft-prewarm android jar ready udid={udid[:12]}",
                flush=True,
            )
            return
        ok, msg = scrcpyclients.push_server_to_device(udid)
        if ok:
            print(
                f"[runner] soft-prewarm android pushed jar udid={udid[:12]}",
                flush=True,
            )
        else:
            _log.debug("soft-prewarm android push jar %s: %s", udid, msg)
    except Exception as exc:  # noqa: BLE001
        _log.debug("soft-prewarm android %s: %s", udid, exc)


def soft_prewarm_ios(udid: str) -> None:
    """占用后检查 runtime + MJPEG；未就绪时不并行 prep（避免双开 WDA）。"""
    if _recently_soft_prewarmed(udid):
        return
    try:
        from autopilot_platform.ap.mobile.ios_bootstrap import mjpeg_alive
        from autopilot_platform.ap.runtime.device_runtime import peek_device_runtime

        rt = peek_device_runtime(udid)
        if rt is not None and mjpeg_alive(rt.ports.mjpeg_port, timeout=0.8):
            print(
                f"[runner] soft-prewarm ios skip udid={udid[:12]} (runtime+mjpeg ready)",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        _log.debug("soft-prewarm ios %s: %s", udid, exc)


def prewarm_webrtc_stack() -> None:
    """轻量预热 AsyncRunner/aiortc（不调用 PeerManager.handle_offer，避免与远控抢 loop）。"""
    global _webrtc_warmed
    with _webrtc_warm_lock:
        if _webrtc_warmed:
            return
    t0 = time.monotonic()
    try:
        from .android.webrtc.async_runner import get_runner

        runner = get_runner()

        async def _warm_imports() -> bool:
            import importlib

            aiortc = importlib.import_module("aiortc")
            caps = aiortc.RTCRtpSender.getCapabilities("video")
            # 预加载远控 answer 路径上的模块，但不创建 PeerSession。
            from .android.webrtc import video_track  # noqa: F401

            return caps is not None

        runner.run_sync(_warm_imports(), timeout=15.0)
        elapsed = time.monotonic() - t0
        with _webrtc_warm_lock:
            _webrtc_warmed = True
        print(f"[runner] webrtc prewarm ok ({elapsed:.2f}s)", flush=True)
    except Exception as exc:  # noqa: BLE001
        _log.warning("webrtc prewarm failed: %s", exc)


def webrtc_stack_ready() -> bool:
    with _webrtc_warm_lock:
        return _webrtc_warmed


def prewarm_android_scrcpy(udid: str) -> None:
    """开远控时并行 scrcpy 冷启动（受 ColdStartGate 限流）。"""
    try:
        from .android import scrcpyclients

        if scrcpyclients.peek_client(udid) is not None:
            print(
                f"[runner] scrcpy prewarm skip udid={udid[:12]} (client alive)",
                flush=True,
            )
            return
    except Exception as exc:  # noqa: BLE001
        _log.debug("scrcpy prewarm peek %s: %s", udid, exc)

    ensure_adb_daemon()
    t0 = time.monotonic()
    try:
        from .android import scrcpyclients

        client = scrcpyclients.get_client(udid)
        if client is not None and getattr(client, "alive", False):
            print(
                f"[runner] scrcpy prewarm udid={udid[:12]} "
                f"({time.monotonic() - t0:.2f}s)",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        _log.debug("scrcpy prewarm %s: %s", udid, exc)


def prewarm_ios_remote(udid: str) -> None:
    soft_prewarm_ios(udid)


def drain_prewarm_hints(hints: list[dict[str, Any]]) -> None:
    for hint in hints or []:
        udid = str(hint.get("udid") or "")
        platform = str(hint.get("platform") or "").lower()
        if not udid:
            continue
        if platform == "android":
            threading.Thread(
                target=soft_prewarm_android,
                args=(udid,),
                name=f"soft-prewarm-{udid[:8]}",
                daemon=True,
            ).start()
        elif platform == "ios":
            threading.Thread(
                target=soft_prewarm_ios,
                args=(udid,),
                name=f"soft-prewarm-ios-{udid[:8]}",
                daemon=True,
            ).start()
