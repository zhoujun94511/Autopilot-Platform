"""iOS 远控控制页：go-ios 无障碍 + WDA 弹窗/键入/截图。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from autopilot_platform.ap.keywords.registry import KeywordError
from autopilot_platform.runner.remote.ios import accessibility, control_ops
from autopilot_platform.runner.remote.ios.command_dispatch import dispatch
from autopilot_platform.runner.remote.shared.command_protocol import (
    is_reliable_command_name,
    normalize_reliable_command,
)


def test_afc_src_candidates_add_slash_and_documents():
    from autopilot_platform.runner.remote.ios.file_ops import afc_src_candidates

    media = afc_src_candidates("DCIM/100APPLE/IMG_0001.JPG")
    assert "DCIM/100APPLE/IMG_0001.JPG" in media
    assert "/DCIM/100APPLE/IMG_0001.JPG" in media
    docs = afc_src_candidates("foo.png", app="com.example.app")
    assert "/Documents/foo.png" in docs
    root = afc_src_candidates(".", app="com.example.app")
    assert root == ["/Documents"]


def test_wda_press_button_timeout_is_short():
    from autopilot_platform.ap.keywords.mobile.wda_client import WdaClient

    seen: dict[str, object] = {}

    def fake_post(path: str, body: dict, timeout=None):
        seen["path"] = path
        seen["body"] = body
        seen["timeout"] = timeout

    client = WdaClient.__new__(WdaClient)
    client._post = fake_post  # type: ignore[method-assign]
    client.press_button("home")
    assert seen["path"] == "/wda/pressButton"
    assert seen["body"] == {"name": "home"}
    assert seen["timeout"] == 3.0


def test_command_job_lane_keeps_home_off_file_queue():
    from autopilot_platform.runner.remote.ios.session import command_job_lane

    assert command_job_lane("home") == "wda"
    assert command_job_lane("press_button") == "wda"
    assert command_job_lane("file.pull") == "aux"
    assert command_job_lane("file.list") == "aux"
    assert command_job_lane("accessibility") == "aux"
    assert command_job_lane("app.list") == "aux"


def test_accessibility_parses_goios_enabled_json():
    assert accessibility._parse_enabled('{"AssistiveTouchEnabled": true}\n') is True
    assert accessibility._parse_enabled('noise\n{"VoiceOverEnabled": false}\n') is False
    assert accessibility._parse_enabled("not json") is None


def test_accessibility_rejects_unknown_feature():
    try:
        accessibility.run("UDID", "unknown")
    except ValueError as exc:
        assert "未知无障碍项" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_accessibility_invokes_goios_like_flask():
    completed = SimpleNamespace(returncode=0, stdout='{"ZoomEnabled": true}\n', stderr="")
    with (
        patch(
            "autopilot_platform.runner.remote.ios.accessibility.resolve_go_ios",
            return_value="ios.exe",
        ),
        patch(
            "autopilot_platform.runner.remote.ios.accessibility.hidden_run",
            return_value=completed,
        ) as run,
    ):
        result = accessibility.run("00008140-UDID", "zoom", "toggle")
    run.assert_called_once()
    cmd = run.call_args.args[0]
    assert cmd == ["ios.exe", "--udid", "00008140-UDID", "zoom", "toggle"]
    assert result == {
        "feature": "zoom",
        "action": "toggle",
        "enabled": True,
        "ok": True,
    }


def test_control_ops_alert_and_keys():
    wda = MagicMock()
    wda.alert_text.return_value = "允许访问？"
    wda.alert_buttons.return_value = ["允许", "不允许"]
    alert = control_ops.get_alert(wda)
    assert alert["present"] is True
    assert alert["buttons"] == ["允许", "不允许"]

    wda.alert_text.side_effect = KeywordError("no alert")
    empty = control_ops.get_alert(wda)
    assert empty["present"] is False

    control_ops.input_key(wda, "enter")
    wda.send_keys.assert_called_with("\n")

    shot = control_ops.screenshot(SimpleNamespace(screenshot_png=lambda: b"\x89PNG"))
    assert shot["mime"] == "image/png"
    assert shot["image"].startswith("data:image/png;base64,")

    try:
        control_ops.screenshot(SimpleNamespace(screenshot_png=lambda: b""))
    except RuntimeError:
        pass
    else:
        raise AssertionError("empty screenshot should fail")


def test_ios_dispatch_accessibility_and_control_commands():
    wda = MagicMock()
    wda.alert_text.return_value = ""
    wda.screenshot_png.return_value = b"png"
    replies: list[dict] = []

    with patch(
        "autopilot_platform.runner.remote.ios.accessibility.run",
        return_value={
            "feature": "assistivetouch",
            "action": "toggle",
            "enabled": True,
            "ok": True,
        },
    ) as run:
        dispatch(
            wda,
            "UDID-1",
            {
                "t": "accessibility",
                "feature": "assistivetouch",
                "action": "toggle",
                "request_id": "a11y-1",
            },
            replies.append,
        )
    run.assert_called_once_with("UDID-1", "assistivetouch", "toggle")
    assert replies[-1]["t"] == "accessibility.result"
    assert replies[-1]["enabled"] is True
    assert replies[-1]["request_id"] == "a11y-1"

    dispatch(wda, "UDID-1", {"t": "alert.get", "request_id": "al-1"}, replies.append)
    assert replies[-1]["t"] == "alert.result"
    assert replies[-1]["present"] is False

    dispatch(
        wda,
        "UDID-1",
        {"t": "input.text", "text": "hello", "request_id": "in-1"},
        replies.append,
    )
    wda.send_keys.assert_called_with("hello")
    assert replies[-1]["t"] == "input.ack"

    dispatch(wda, "UDID-1", {"t": "device.screenshot", "request_id": "ss-1"}, replies.append)
    assert replies[-1]["t"] == "device.screenshot.result"
    assert str(replies[-1]["image"]).startswith("data:image/png;base64,")


def test_accessibility_commands_are_reliable():
    assert is_reliable_command_name("accessibility")
    assert is_reliable_command_name("alert.get")
    assert is_reliable_command_name("input.text")
    assert is_reliable_command_name("device.screenshot")
    event = normalize_reliable_command(
        {
            "channel": "command",
            "type": "request",
            "name": "accessibility",
            "request_id": "req-a11y",
            "payload": {
                "t": "accessibility",
                "feature": "voiceover",
                "action": "get",
            },
        }
    )
    assert event is not None
    assert event["t"] == "accessibility"
    assert event["feature"] == "voiceover"
