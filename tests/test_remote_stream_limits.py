from autopilot_platform.runner.remote.shared.stream_limits import (
    sanitize_android_stream_config,
    sanitize_ios_stream_config,
)


def test_android_stream_limits_clamp_dangerous_values():
    out = sanitize_android_stream_config(
        {
            "bitrate": 999_999_999,
            "max_fps": 240,
            "max_width": 8192,
            "i_frame_interval": 60,
        }
    )
    assert out["bitrate"] == 20_000_000
    assert out["max_fps"] == 60
    assert out["max_width"] == 1920
    assert out["i_frame_interval"] == 8


def test_android_stream_limits_raise_tiny_width_and_bitrate():
    out = sanitize_android_stream_config(
        {"bitrate": 1, "max_width": 120, "max_fps": 0, "i_frame_interval": 0}
    )
    assert out["bitrate"] == 500_000
    assert out["max_width"] == 480
    assert out["max_fps"] == 5
    assert out["i_frame_interval"] == 1


def test_android_native_width_stays_zero():
    assert sanitize_android_stream_config({"max_width": 0})["max_width"] == 0


def test_ios_stream_limits_clamp_jpeg_and_fps():
    out = sanitize_ios_stream_config({"max_fps": 120, "jpeg_quality": 1, "mjpeg_scaling": 9})
    assert out["max_fps"] == 30
    assert out["jpeg_quality"] == 10
    assert out["mjpeg_scaling"] == 25
