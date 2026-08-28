from __future__ import annotations

import zipfile

from autopilot_platform.ap.mobile import ios_bootstrap


def test_resolve_go_ios_extracts_bundled_zip_before_path(tmp_path, monkeypatch):
    resources = tmp_path / "re_go_ios"
    archive = resources / "utils" / "go-ios-win.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ios.exe", b"bundled")

    monkeypatch.setattr(ios_bootstrap, "_IOS_RES", resources)
    monkeypatch.setattr(ios_bootstrap.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ios_bootstrap,
        "_goios_usable",
        lambda path: bool(path and path.is_file()),
    )
    monkeypatch.setattr(
        ios_bootstrap.shutil,
        "which",
        lambda _name: str(tmp_path / "path" / "ios.exe"),
    )

    resolved = ios_bootstrap.resolve_go_ios()

    assert resolved == resources / "runpath" / "win" / "ios.exe"
    assert resolved is not None
    assert resolved.read_bytes() == b"bundled"


def test_latest_crash_file_picks_newest_matching_report():
    listing = (
        '{"level":"info","msg":"connected"}\n'
        '{"files":["Other-2026-08-19-210000.ips",'
        '"WebDriverAgentRunner-Runner-2026-08-19-203220.ips",'
        '"WebDriverAgentRunner-Runner-2026-08-19-205959.ips"],"length":3}\n'
    )

    assert (
        ios_bootstrap.latest_crash_file(listing)
        == "WebDriverAgentRunner-Runner-2026-08-19-205959.ips"
    )
    assert ios_bootstrap.latest_crash_file('{"files":null,"length":0}') == ""


def test_parse_crash_termination_reports_missing_symbol():
    report = (
        '{"app_name":"WebDriverAgentRunner-Runner","os_version":"iPhone OS 18.6.2"}\n'
        '{\n'
        '  "exception": {"type": "EXC_CRASH", "signal": "SIGABRT"},\n'
        '  "termination": {"namespace": "DYLD", "indicator": "Symbol missing",\n'
        '    "reasons": ["Symbol not found: _OBJC_CLASS_$_XCTCommandLineToolHelper",\n'
        '      "Expected in: /System/Developer/Library/Frameworks/XCTest.framework/XCTest"]}\n'
        '}\n'
    )

    reason = ios_bootstrap.parse_crash_termination(report)

    assert "Symbol not found: _OBJC_CLASS_$_XCTCommandLineToolHelper" in reason
    assert ios_bootstrap.parse_crash_termination("not json") == ""


def test_resolve_go_ios_rejects_zip_path_traversal(tmp_path, monkeypatch):
    resources = tmp_path / "re_go_ios"
    archive = resources / "utils" / "go-ios-win.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../ios.exe", b"unsafe")

    monkeypatch.setattr(ios_bootstrap, "_IOS_RES", resources)
    monkeypatch.setattr(ios_bootstrap.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        ios_bootstrap,
        "_goios_usable",
        lambda path: bool(path and path.is_file()),
    )
    monkeypatch.setattr(ios_bootstrap.shutil, "which", lambda _name: None)

    assert ios_bootstrap.resolve_go_ios() is None
    assert not (resources / "runpath" / "ios.exe").exists()
