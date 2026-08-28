"""远控流参数安全窗。

DataChannel / WS 不走 Pydantic schema，必须在 Runner 侧再夹一次，
避免乱填码率/分辨率把 scrcpy 或 WDA 打崩。
"""

from __future__ import annotations

from typing import Any

ANDROID_BITRATE = (500_000, 20_000_000)
ANDROID_MAX_FPS = (5, 60)
ANDROID_MAX_WIDTH = (0, 1920)
ANDROID_MIN_POSITIVE_WIDTH = 480
ANDROID_IFRAME = (1, 8)
IOS_MAX_FPS = (1, 30)
IOS_JPEG = (10, 90)
IOS_SCALE = (25, 100)


def clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def sanitize_android_stream_config(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    if raw.get("bitrate") is not None:
        out["bitrate"] = clamp_int(raw["bitrate"], *ANDROID_BITRATE, 4_000_000)
    if raw.get("max_fps") is not None:
        out["max_fps"] = clamp_int(raw["max_fps"], *ANDROID_MAX_FPS, 60)
    if raw.get("max_width") is not None:
        width = clamp_int(raw["max_width"], *ANDROID_MAX_WIDTH, 0)
        if 0 < width < ANDROID_MIN_POSITIVE_WIDTH:
            width = ANDROID_MIN_POSITIVE_WIDTH
        out["max_width"] = width
    if raw.get("i_frame_interval") is not None:
        out["i_frame_interval"] = clamp_int(
            raw["i_frame_interval"], *ANDROID_IFRAME, 2
        )
    return out


def sanitize_ios_stream_config(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    if raw.get("max_fps") is not None:
        out["max_fps"] = clamp_int(raw["max_fps"], *IOS_MAX_FPS, 12)
    if raw.get("jpeg_quality") is not None:
        out["jpeg_quality"] = clamp_int(raw["jpeg_quality"], *IOS_JPEG, 45)
    if raw.get("mjpeg_scaling") is not None or raw.get("jpeg_scale") is not None:
        out["mjpeg_scaling"] = clamp_int(
            raw.get("mjpeg_scaling", raw.get("jpeg_scale")),
            *IOS_SCALE,
            60,
        )
    return out
