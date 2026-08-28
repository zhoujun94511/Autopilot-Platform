"""远控资源回收：会话结束不留隧道/转发/临时文件，且不误伤并行槽位。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autopilot_platform.ap.mobile import ios_bootstrap
from autopilot_platform.runner.remote.android import file_transfer
from autopilot_platform.runner.remote.ios import app_ops


def test_reclaim_stale_skips_default_agent_when_other_tunnel_alive(monkeypatch):
    killed_ports: list[int] = []

    monkeypatch.setattr(
        ios_bootstrap, "kill_goios_tunnel_agents", lambda **_kw: [11]
    )
    monkeypatch.setattr(
        ios_bootstrap,
        "other_goios_tunnel_running",
        lambda **_kw: True,
    )
    monkeypatch.setattr(
        ios_bootstrap,
        "kill_listeners",
        lambda port, **_kw: killed_ports.append(port) or [port],
    )

    ios_bootstrap.reclaim_stale_local_ios_prep(
        info_port=28110, wda_port=8101, mjpeg_port=9101
    )

    assert 28110 in killed_ports
    assert 8101 in killed_ports
    assert 9101 in killed_ports
    assert ios_bootstrap._GOIOS_DEFAULT_AGENT_PORT not in killed_ports


def test_reclaim_stale_clears_default_agent_when_alone(monkeypatch):
    killed_ports: list[int] = []

    monkeypatch.setattr(
        ios_bootstrap, "kill_goios_tunnel_agents", lambda **_kw: []
    )
    monkeypatch.setattr(
        ios_bootstrap,
        "other_goios_tunnel_running",
        lambda **_kw: False,
    )
    monkeypatch.setattr(
        ios_bootstrap,
        "kill_listeners",
        lambda port, **_kw: killed_ports.append(port) or [],
    )

    ios_bootstrap.reclaim_stale_local_ios_prep(
        info_port=28100, wda_port=8100, mjpeg_port=9100
    )

    assert ios_bootstrap._GOIOS_DEFAULT_AGENT_PORT in killed_ports


def test_ios_prep_stop_reclaims_session_ports_and_tunnel(monkeypatch, tmp_path):
    calls: dict[str, list] = {"tunnel": [], "ports": []}
    log_path = tmp_path / "runwda.log"
    log_path.write_text("authorized", encoding="utf-8")

    monkeypatch.setattr(
        ios_bootstrap,
        "kill_goios_tunnel_agents",
        lambda **kw: calls["tunnel"].append(kw) or [],
    )
    monkeypatch.setattr(ios_bootstrap, "is_port_listening", lambda _p: True)
    monkeypatch.setattr(
        ios_bootstrap,
        "other_goios_tunnel_running",
        lambda **_kw: False,
    )
    monkeypatch.setattr(
        ios_bootstrap,
        "kill_listeners",
        lambda port, **_kw: calls["ports"].append(port) or [],
    )

    prep = ios_bootstrap.IosDevicePrep(
        "UDID",
        "com.example.wda",
        info_port=28120,
        wda_port=8102,
        mjpeg_port=9102,
    )
    prep._wda_log = str(log_path)
    prep._procs = [SimpleNamespace(pid=99, poll=lambda: None, terminate=lambda: None)]

    prep.stop()

    assert any(c.get("info_port") == 28120 for c in calls["tunnel"])
    assert set(calls["ports"]) >= {28120, 8102, 9102, ios_bootstrap._GOIOS_DEFAULT_AGENT_PORT}
    assert prep._procs == []
    assert not log_path.exists()


def test_ensure_forward_port_uses_devnull(monkeypatch):
    spawned: list[dict] = []

    class _Proc:
        def __init__(self) -> None:
            self._n = 0

        @staticmethod
        def poll():
            return None

    def fake_popen(cmd, **kwargs):
        spawned.append({"cmd": cmd, **kwargs})
        return _Proc()

    monkeypatch.setattr(ios_bootstrap.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ios_bootstrap, "is_port_listening", lambda _p: True)

    prep = ios_bootstrap.IosDevicePrep("UDID", "com.example.wda")
    assert prep.ensure_forward_port(8100, timeout=1) is True
    assert spawned
    assert spawned[0]["stdout"] is ios_bootstrap.subprocess.DEVNULL
    assert spawned[0]["stderr"] is ios_bootstrap.subprocess.DEVNULL


def test_android_file_transfer_cleanup_all(tmp_path, monkeypatch):
    monkeypatch.setattr(file_transfer, "_STAGING_DIR", tmp_path)
    replies: list[dict] = []
    file_transfer.begin(
        {"id": "t1", "name": "a.apk", "size": 3, "remote": "/sdcard/"},
        replies.append,
    )
    path = Path(file_transfer._transfers["t1"].local_path)
    assert path.exists()

    file_transfer.cleanup_all_transfers()

    assert file_transfer._transfers == {}
    assert not path.exists()


def test_ios_app_ops_cleanup_pending_installs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    replies: list[dict] = []
    app_ops.begin_install({"id": "i1", "name": "app.ipa", "size": 4}, replies.append)
    path = Path(app_ops._installs["i1"][1])
    assert path.exists()

    app_ops.cleanup_pending_installs()

    assert app_ops._installs == {}
    assert not path.exists()


def test_goios_name_matches_filters_before_cmdline():
    from autopilot_platform.ap.mobile.ios_bootstrap import _goios_name_matches

    assert _goios_name_matches("ios.exe", "ios.exe")
    assert _goios_name_matches("go-ios", "go-ios")
    assert not _goios_name_matches("python.exe", "ios.exe")
    assert not _goios_name_matches("svchost.exe", "ios.exe")
    assert not _goios_name_matches("", "ios.exe")
