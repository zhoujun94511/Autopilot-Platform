"""Platform create-job CLI（B1-C 镜像）。"""

from __future__ import annotations

import argparse

import pytest

from autopilot_platform.platform.cli_create_job import build_job_body, main


def _ns(**kwargs):
    defaults = dict(
        name="CI Suite",
        platform="android",
        project_id="",
        artifact_id="",
        app_build_id="",
        project_dir="",
        device_udids="",
        entry_paths="",
        parallel=False,
        parallel_workers=0,
        backend_mode="auto",
        web_engine="selenium",
        wda_bundle="",
        preferred_runner_id="",
        webhook_url="",
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_build_job_body_requires_source():
    with pytest.raises(ValueError, match="artifact-id|project-dir"):
        build_job_body(_ns())


def test_build_job_body_ok():
    body = build_job_body(
        _ns(artifact_id="art_1", platform="iOS", device_udids="a,b")
    )
    assert body["artifact_id"] == "art_1"
    assert body["platform"] == "ios"
    assert body["device_udids"] == ["a", "b"]


def test_main_dry_run(capsys):
    code = main(
        ["--artifact-id", "art_x", "--platform", "web", "--dry-run"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "art_x" in out
    assert "web" in out


def test_platform_help_lists_http():
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "autopilot_platform"
        / "platform"
        / "cli_create_job.py"
    ).read_text(encoding="utf-8")
    assert "android|ios|web|http" in text
