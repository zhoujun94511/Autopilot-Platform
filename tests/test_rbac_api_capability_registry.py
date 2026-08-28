"""ARCH-002 最小步：能力 ID ↔ API 路由绑定契约（防 drift）。"""

from __future__ import annotations

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.tenancy.capability_registry import (
    CAPABILITY_IDS,
    CAPABILITY_ROUTE_BINDINGS,
)


def _normalize_openapi_path(path: str) -> str:
    return re.sub(r"\{[^}]+}", "{param}", path)


@pytest.fixture()
def openapi_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "cap_reg.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    from autopilot_platform.platform.core.db import reset_engine

    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    spec = app.openapi()
    paths: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                paths.add((method.upper(), _normalize_openapi_path(path)))
    reset_engine()
    reload_runtime_config()
    return paths


def test_registry_capability_ids_are_known():
    for binding in CAPABILITY_ROUTE_BINDINGS:
        assert binding.capability_id in CAPABILITY_IDS, binding


def test_registry_routes_exist_in_openapi(openapi_paths):
    missing: list[str] = []
    for b in CAPABILITY_ROUTE_BINDINGS:
        norm = _normalize_openapi_path(b.path)
        if (b.method, norm) not in openapi_paths:
            missing.append(f"{b.method} {norm} ({b.capability_id})")
    assert not missing, "注册表路由在 OpenAPI 中缺失:\n" + "\n".join(missing)


def test_scoped_token_binding_is_platform_admin_only():
    hit = [
        b
        for b in CAPABILITY_ROUTE_BINDINGS
        if b.capability_id == "cap.ide.runner.start_scoped"
    ]
    assert len(hit) == 1
    assert hit[0].guard == "platform_admin"
    assert hit[0].method == "POST"
    assert "scoped-token" in hit[0].path


def test_purge_routes_platform_admin_only():
    purge_caps = {
        "cap.artifacts.purge",
        "cap.app_builds.purge",
        "cap.reports.purge",
    }
    for b in CAPABILITY_ROUTE_BINDINGS:
        if b.capability_id in purge_caps:
            assert b.guard == "platform_admin", b
    assert any(
        b.capability_id == "cap.reports.purge"
        and b.path == "/api/v1/reports/purge"
        for b in CAPABILITY_ROUTE_BINDINGS
    )
