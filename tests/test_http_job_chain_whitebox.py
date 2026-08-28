"""HTTP 作为 Job 平台的白盒：schema 剥离 → env 注入 → execute 接线。

不启 FastAPI / 真机。覆盖 JobCreate / ScheduleCreate 与 Runner 注入口。
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from autopilot_platform.ap.keywords.context import ExecutionContext
from autopilot_platform.ap.keywords.http.env import api_env_use, apply_job_http_env
from autopilot_platform.ap.keywords.http.session import http_session_begin, http_session_end
from autopilot_platform.core.job_platforms import apply_deviceless_run_target
from autopilot_platform.core.schemas import JobCreate, ScheduleCreate
from autopilot_platform.runner.execute import execute_job
from autopilot_platform.runner.local_devices import probe_host_capabilities


def test_job_create_http_strips_mobile_keeps_profile():
    body = JobCreate(
        name="api",
        project_dir="/tmp/http-suite",
        platform="HTTP",
        backend_mode="staging",
        device_udids=["should-strip"],
        parallel=True,
        parallel_workers=4,
        wda_bundle="com.wda",
        app_build_id="apk-1",
        web_engine="playwright",
    )
    assert body.platform == "http"
    assert body.backend_mode == "staging"
    assert body.device_udids == []
    assert body.parallel is False
    assert body.parallel_workers == 0
    assert body.wda_bundle == ""
    assert body.app_build_id is None
    assert body.web_engine == "selenium"


def test_job_create_web_keeps_playwright_and_browser():
    body = JobCreate(
        name="web",
        project_dir="/tmp/web-suite",
        platform="web",
        backend_mode="chrome",
        web_engine="playwright",
        device_udids=["nope"],
        parallel=True,
        app_build_id="apk-1",
    )
    assert body.device_udids == []
    assert body.parallel is False
    assert body.app_build_id is None
    assert body.web_engine == "playwright"
    assert body.backend_mode == "chrome"


def test_job_create_android_keeps_devices():
    body = JobCreate(
        name="and",
        project_dir="/tmp/and-suite",
        platform="android",
        backend_mode="uia2",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=2,
        app_build_id="apk-1",
    )
    assert body.device_udids == ["u1"]
    assert body.parallel is True
    assert body.parallel_workers == 2
    assert body.app_build_id == "apk-1"
    assert body.backend_mode == "uia2"


def test_job_create_accepts_long_http_profile():
    from autopilot_platform.core.job_platforms import BACKEND_MODE_MAX_LEN
    from autopilot_platform.platform.core.models import JobRow, ScheduleRow

    profile = "pre-production-us-east-1"
    assert len(profile) > 16
    body = JobCreate(
        name="api",
        project_dir="/tmp/http-suite",
        platform="http",
        backend_mode=profile,
    )
    assert body.backend_mode == profile
    assert JobRow.__table__.c.backend_mode.type.length == BACKEND_MODE_MAX_LEN
    assert ScheduleRow.__table__.c.backend_mode.type.length == BACKEND_MODE_MAX_LEN
    with pytest.raises(ValidationError):
        JobCreate(
            name="api",
            project_dir="/tmp/http-suite",
            platform="http",
            backend_mode="x" * (BACKEND_MODE_MAX_LEN + 1),
        )


def test_job_create_rejects_unknown_platform():
    with pytest.raises(ValidationError) as exc:
        JobCreate(name="x", project_dir="/tmp/x", platform="ftp")
    assert "platform must be one of" in str(exc.value)


def test_schedule_create_http_strips_mobile_keeps_profile():
    body = ScheduleCreate(
        name="nightly-api",
        project_dir="/tmp/http-suite",
        platform="http",
        backend_mode="staging",
        web_engine="playwright",
        device_udids=["should-strip"],
        parallel=True,
        parallel_workers=3,
        wda_bundle="com.wda",
        app_build_id="apk-1",
        delay_sec=0,
        interval_sec=0,
        repeat=1,
    )
    assert body.platform == "http"
    assert body.backend_mode == "staging"
    assert body.device_udids == []
    assert body.parallel is False
    assert body.parallel_workers == 0
    assert body.wda_bundle == ""
    assert body.app_build_id is None
    assert body.web_engine == "selenium"


def test_apply_job_http_env_unknown_profile_raises(tmp_path):
    from autopilot_platform.ap.keywords.registry import KeywordError

    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n",
        encoding="utf-8",
    )
    with pytest.raises(KeywordError, match="no-such"):
        apply_job_http_env({}, project_dir=str(tmp_path), profile="no-such")


def test_apply_job_http_env_to_session_and_api_env_use(tmp_path):
    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  staging:\n    base_url: https://api.example.test\n"
        "    vars:\n      api_token: t-stg\n",
        encoding="utf-8",
    )
    base: dict = {}
    apply_job_http_env(base, project_dir=str(tmp_path), profile="staging")
    ctx = ExecutionContext()
    for key, value in base.items():
        ctx.set_var(key, value)
    http_session_begin(ctx)
    assert ctx.http_session.base_url == "https://api.example.test"
    http_session_end(ctx)

    ctx2 = ExecutionContext()
    ctx2.set_var("__project_path__", str(tmp_path))
    ctx2.set_var("__http_env_profile__", "staging")
    api_env_use(ctx2)
    assert ctx2.get_var("base_url") == "https://api.example.test"
    assert ctx2.get_var("api_token") == "t-stg"


def test_execute_job_http_branch_wired():
    src = inspect.getsource(execute_job)
    assert 'plat == "http"' in src
    assert "apply_job_http_env" in src


def test_runner_capabilities_always_include_http():
    caps, _backends = probe_host_capabilities()
    assert "http" in caps


def test_apply_deviceless_is_public_job_platforms_api():
    from types import SimpleNamespace

    row = SimpleNamespace(
        platform="http",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=1,
        wda_bundle="x",
        app_build_id="apk",
        web_engine="playwright",
        backend_mode="dev",
    )
    apply_deviceless_run_target(row)
    assert row.device_udids == []
    assert row.backend_mode == "dev"
    assert row.web_engine == "selenium"
