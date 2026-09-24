"""APJF HEVC 配置/访问单元不进入 JPEG HTTP 槽。"""

from autopilot_platform.runner.remote.shared.frame_bus import (
    binary_frame_to_http_payload,
    pack_binary_frame,
    pack_hevc_au,
    pack_hevc_config,
    unpack_binary_frame,
)


def test_jpeg_frame_unchanged():
    packed = pack_binary_frame(b"\xff\xd8\xff\xd9", width=12, height=16)
    parsed = unpack_binary_frame(packed)
    assert parsed is not None
    assert parsed["type"] == "frame"
    assert parsed["jpeg"] == b"\xff\xd8\xff\xd9"
    http = binary_frame_to_http_payload(packed)
    assert http is not None
    assert http["mime"] == "image/jpeg"


def test_hevc_gap_marks_next_key_as_reset():
    from autopilot_platform.runner.remote.shared.ws_client import (
        RunnerRemoteWebSocket,
        _mark_hevc_reset,
    )

    key = b"APJF" + bytes([1, 3, 0, 0, 0, 0]) + b"\x00\x00\x00\x01\x00"
    assert _mark_hevc_reset(key)[14] == 2
    delta = b"APJF" + bytes([1, 3, 0, 0, 0, 0]) + b"\x00\x00\x00\x01\x01"
    ws = RunnerRemoteWebSocket("http://127.0.0.1", "token", "sid")
    for _ in range(24):
        assert ws._enqueue_hevc(delta) is True
    assert ws._enqueue_hevc(delta) is False
    assert ws._hevc_gap is True
    assert ws._enqueue_hevc(key) is True
    assert any(len(item) >= 15 and item[14] == 2 for item in ws._hevc_pending)
    assert ws._hevc_gap is False


def test_direct_send_marks_gap_key():
    from autopilot_platform.runner.remote.shared.ws_client import RunnerRemoteWebSocket

    key = b"APJF" + bytes([1, 3, 0, 0, 0, 0]) + b"\x00\x00\x00\x01\x00"
    sent: list[bytes] = []

    class _Sock:
        @staticmethod
        def send(payload: bytes) -> None:
            sent.append(payload)

    ws = RunnerRemoteWebSocket("http://127.0.0.1", "token", "sid")
    ws._connected.set()
    ws._socket = _Sock()
    ws._hevc_gap = True
    assert ws.send_hevc(key) is True
    assert sent and sent[-1][14] == 2
    assert ws._hevc_gap is False


def test_drain_failure_sets_gap():
    from autopilot_platform.runner.remote.shared.ws_client import RunnerRemoteWebSocket

    delta = b"APJF" + bytes([1, 3, 0, 0, 0, 0]) + b"\x00\x00\x00\x01\x01"

    class _Sock:
        def send(self, payload: bytes) -> None:
            raise OSError("down")

    ws = RunnerRemoteWebSocket("http://127.0.0.1", "token", "sid")
    ws._hevc_pending.append(delta)
    try:
        ws._drain_pending_hevc_locked(_Sock())
    except OSError:
        pass
    else:
        raise AssertionError("drain should raise")
    assert ws._hevc_gap is True
    assert len(ws._hevc_pending) == 0


def test_hevc_config_and_au_skip_http_slot():
    config = pack_hevc_config("hev1.1.6.L150.B0", b"\x01\x02\x03")
    parsed = unpack_binary_frame(config)
    assert parsed is not None
    assert parsed["type"] == "hevc"
    assert parsed["hevc_kind"] == 2
    assert parsed["packet"].split(b"\x00", 1)[0] == b"hev1.1.6.L150.B0"
    assert binary_frame_to_http_payload(config) is None

    au = pack_hevc_au(b"\x00\x00\x00\x01\x00")
    parsed_au = unpack_binary_frame(au)
    assert parsed_au is not None
    assert parsed_au["hevc_kind"] == 3
    assert binary_frame_to_http_payload(au) is None
