"""PeerManager / PeerSession 重协商回调迁移。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autopilot_platform.runner.remote.android.webrtc import peer_manager as pm_mod


def _fake_callbacks() -> pm_mod.PeerSessionCallbacks:
    return pm_mod.PeerSessionCallbacks(
        on_input_message=lambda _msg: None,
        on_adb_message=lambda _msg: None,
        on_ice_local=lambda _c: None,
        on_closed=lambda _s: None,
        on_input_open=lambda: None,
    )


def test_peer_session_snapshot_restore_roundtrip() -> None:
    saved = _fake_callbacks()

    real = pm_mod.PeerSession.__new__(pm_mod.PeerSession)
    real._on_input_message = None
    real._on_adb_message = None
    real._on_ice_local = None
    real._on_closed = None
    real._on_input_open = None
    real.input_channel = None

    real.restore_callbacks(saved)
    assert real._on_input_message is saved.on_input_message
    assert real._on_adb_message is saved.on_adb_message
    assert real._on_ice_local is saved.on_ice_local
    assert real._on_closed is saved.on_closed
    assert real._on_input_open is saved.on_input_open

    snap = real.snapshot_callbacks()
    assert snap == saved


def test_handle_offer_migrates_callbacks_on_renegotiation() -> None:
    saved = _fake_callbacks()
    old = MagicMock()
    old.pc.connectionState = "connected"
    old.pc.remoteDescription = object()
    old.snapshot_callbacks.return_value = saved

    new = MagicMock()
    new.handle_offer = MagicMock(return_value={"sdp": "v=0", "type": "answer"})

    mgr = pm_mod.PeerManager()
    mgr._sessions[("sid-1", "dev-1")] = old

    with patch.object(mgr, "close") as close_mock, patch.object(
        mgr, "get_or_create", return_value=new
    ), patch.object(mgr, "runner") as runner_mock:
        runner_mock.return_value.run_sync.side_effect = lambda coro, timeout=15: coro
        out = mgr.handle_offer("sid-1", "dev-1", "offer-sdp")

    close_mock.assert_called_once_with("sid-1", "dev-1")
    old.snapshot_callbacks.assert_called_once_with()
    new.restore_callbacks.assert_called_once_with(saved)
    assert out == {"sdp": "v=0", "type": "answer"}


def test_handle_offer_skips_migration_on_first_negotiation() -> None:
    new = MagicMock()
    new.handle_offer = MagicMock(return_value={"sdp": "v=0", "type": "answer"})

    mgr = pm_mod.PeerManager()

    with patch.object(mgr, "close") as close_mock, patch.object(
        mgr, "get", return_value=None
    ), patch.object(mgr, "get_or_create", return_value=new), patch.object(
        mgr, "runner"
    ) as runner_mock:
        runner_mock.return_value.run_sync.side_effect = lambda coro, timeout=15: coro
        mgr.handle_offer("sid-1", "dev-1", "offer-sdp")

    close_mock.assert_not_called()
    new.restore_callbacks.assert_called_once()
    empty = new.restore_callbacks.call_args[0][0]
    assert empty == pm_mod.PeerSessionCallbacks(None, None, None, None, None)


def test_restore_callbacks_replays_input_open_when_channel_already_open() -> None:
    opened: list[str] = []
    saved = pm_mod.PeerSessionCallbacks(None, None, None, None, lambda: opened.append("ok"))

    real = pm_mod.PeerSession.__new__(pm_mod.PeerSession)
    real._on_input_open = None
    real.input_channel = type("Ch", (), {"readyState": "open"})()

    real.restore_callbacks(saved)
    assert opened == ["ok"]


def test_peer_session_input_channel_ready() -> None:
    sess = pm_mod.PeerSession.__new__(pm_mod.PeerSession)
    sess.input_channel = None
    assert sess.input_channel_ready() is False
    sess.input_channel = type("Ch", (), {"readyState": "open"})()
    assert sess.input_channel_ready() is True
    sess.input_channel = type("Ch", (), {"readyState": "connecting"})()
    assert sess.input_channel_ready() is False
