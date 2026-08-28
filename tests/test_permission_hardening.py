"""权限硬化：Token 拆分、Runner scope、设备 org 可见性、ops_admin 扩展点。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.auth import AuthContext, runner_scope_allows_project
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.auth import is_ops_admin
from autopilot_platform.platform.tenancy.projects import is_platform_admin
from autopilot_platform.platform.core.settings import (
    allow_legacy_token_admin,
    emit_insecure_defaults_startup_banner,
    insecure_defaults_reasons,
    is_exposed_bind_host,
    is_loopback_bind_host,
    is_production,
    require_admin_token_split,
    using_insecure_defaults,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "perm.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "admin-ops-token")
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_REQUIRE_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _admin_headers(client: TestClient) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_settings_production_flags(monkeypatch):
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_REQUIRE_ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", raising=False)
    assert is_production() is False
    assert require_admin_token_split() is False
    assert allow_legacy_token_admin() is False
    monkeypatch.setenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    assert allow_legacy_token_admin() is True
    assert is_loopback_bind_host("127.0.0.1") is True
    assert is_exposed_bind_host("0.0.0.0") is True
    monkeypatch.setenv("MC_ENV", "production")
    assert is_production() is True
    assert require_admin_token_split() is True
    monkeypatch.setenv("MC_ENV", "dev")
    monkeypatch.setenv("MC_REQUIRE_ADMIN_API_TOKEN", "1")
    assert require_admin_token_split() is True


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MC_API_TOKEN", "dev-mc-token"),
        ("MC_JWT_SECRET", "dev-mc-jwt-secret-change-me-32b!!"),
        ("MC_ADMIN_PASSWORD", "admin"),
        ("MC_ADMIN_API_TOKEN", None),
        ("MC_ADMIN_API_TOKEN", "strong-runner-token"),
    ],
)
def test_production_rejects_insecure_or_unsplit_credentials(monkeypatch, name, value):
    monkeypatch.setenv("MC_ENV", "production")
    monkeypatch.setenv("MC_API_TOKEN", "strong-runner-token")
    monkeypatch.setenv("MC_JWT_SECRET", "strong-jwt-secret-at-least-32-bytes")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "StrongAdmin123")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "strong-admin-token")
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="生产安全配置校验失败"):
        create_app(database_url="sqlite:///:memory:")


def test_development_keeps_default_credential_compatibility(monkeypatch):
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.setenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    for name in (
        "MC_API_TOKEN",
        "MC_JWT_SECRET",
        "MC_ADMIN_PASSWORD",
        "MC_ADMIN_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_engine()
    assert create_app(database_url="sqlite:///:memory:") is not None
    reset_engine()


def test_insecure_defaults_banner_and_reasons(monkeypatch):
    """AUD-2026-06：开发默认凭据时 stderr 横幅可见，强凭据时静默。"""
    from io import StringIO

    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_API_TOKEN", raising=False)
    monkeypatch.delenv("MC_JWT_SECRET", raising=False)
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    assert using_insecure_defaults() is True
    reasons = insecure_defaults_reasons()
    assert any("MC_API_TOKEN" in r for r in reasons)
    buf = StringIO()
    assert emit_insecure_defaults_startup_banner(stream=buf) is True
    text = buf.getvalue()
    assert "INSECURE DEVELOPMENT DEFAULTS" in text
    assert "AUD-2026-06" in text
    assert "deploy/production.env.example" in text

    monkeypatch.setenv("MC_API_TOKEN", "strong-runner-token")
    monkeypatch.setenv("MC_JWT_SECRET", "strong-jwt-secret-at-least-32-bytes")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "StrongAdmin123")
    assert using_insecure_defaults() is False
    assert emit_insecure_defaults_startup_banner(stream=StringIO()) is False


def test_global_token_is_runner_without_legacy_flag(monkeypatch, tmp_path):
    """secure-by-default：无 ADMIN、无 legacy 旗标时，全局 Token 不得访问运维面。"""
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", raising=False)
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.setenv("MC_API_TOKEN", "runner-only-no-legacy")
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "rt.json"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'no-legacy.db').as_posix()}")
    with TestClient(app) as c:
        r = c.get(
            "/api/v1/ops/summary",
            headers={"X-API-Token": "runner-only-no-legacy"},
        )
        assert r.status_code == 403
        # JWT 平台 admin 仍可用
        login = c.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
        )
        assert login.status_code == 200
        ah = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert c.get("/api/v1/ops/summary", headers=ah).status_code == 200
    reset_engine()
    reload_runtime_config()


def test_legacy_flag_restores_implicit_admin(monkeypatch, tmp_path):
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    monkeypatch.setenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.setenv("MC_API_TOKEN", "legacy-admin-token")
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "rt.json"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with TestClient(app) as c:
        r = c.get(
            "/api/v1/ops/summary",
            headers={"X-API-Token": "legacy-admin-token"},
        )
        assert r.status_code == 200
    reset_engine()
    reload_runtime_config()


def test_non_loopback_bind_rejects_insecure_defaults(monkeypatch):
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_HOST", "0.0.0.0")
    for name in (
        "MC_API_TOKEN",
        "MC_JWT_SECRET",
        "MC_ADMIN_PASSWORD",
        "MC_ADMIN_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="非 loopback"):
        create_app(database_url="sqlite:///:memory:")
    reset_engine()


def test_ops_admin_extension_equals_platform_admin():
    admin = AuthContext(kind="user", username="a", user_id="1", role="admin")
    op = AuthContext(kind="user", username="o", user_id="2", role="operator")
    runner = AuthContext(kind="runner", username="r", role="runner", runner_id="r1")
    assert is_platform_admin(admin) and is_ops_admin(admin)
    assert not is_platform_admin(op) and not is_ops_admin(op)
    assert not is_platform_admin(runner) and not is_ops_admin(runner)


def test_execution_token_cannot_hit_ops(client: TestClient):
    r = client.get("/api/v1/ops/summary", headers={"X-API-Token": "runner-global-token"})
    assert r.status_code == 403
    r = client.get("/api/v1/ops/summary", headers={"X-API-Token": "admin-ops-token"})
    assert r.status_code == 200


def test_operator_jwt_cannot_access_runner_control_plane(client: TestClient):
    ah = _admin_headers(client)
    assert client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "plain-operator", "password": "Operator123", "duty": "user"},
    ).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "plain-operator", "password": "Operator123"},
    )
    assert login.status_code == 200
    operator_h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    requests = (
        client.post(
            "/api/v1/runners/register",
            headers=operator_h,
            json={"runner_id": "forged-runner", "hostname": "host"},
        ),
        client.post(
            "/api/v1/runners/heartbeat",
            headers=operator_h,
            json={"runner_id": "forged-runner", "inventory": [], "devices": []},
        ),
        client.post(
            "/api/v1/jobs/claim?runner_id=forged-runner",
            headers=operator_h,
        ),
        client.post(
            "/api/v1/jobs/unknown/running?runner_id=forged-runner",
            headers=operator_h,
        ),
        client.post(
            "/api/v1/jobs/unknown/complete?runner_id=forged-runner",
            headers=operator_h,
            json={"status": "succeeded"},
        ),
        client.post(
            "/api/v1/jobs/unknown/report?runner_id=forged-runner",
            headers=operator_h,
            files={"file": ("result.json", b"{}", "application/json")},
        ),
    )
    assert [response.status_code for response in requests] == [403] * len(requests)


def test_runner_scope_unit(client: TestClient):
    from autopilot_platform.platform.core.db import get_engine
    from sqlalchemy.orm import Session
    from autopilot_platform.platform.core.models import OrganizationRow, ProjectRow

    eng = get_engine()
    with Session(eng) as db:
        oid = f"org-scope-{os.getpid()}-{id(db)}"
        other = f"org-other-{os.getpid()}-{id(db)}"
        db.add(OrganizationRow(id=oid, name="A", created_by="admin"))
        db.add(OrganizationRow(id=other, name="B", created_by="admin"))
        db.add(
            ProjectRow(
                id=f"proj-in-{os.getpid()}",
                name="in",
                org_id=oid,
                owner_user_id="x",
            )
        )
        db.add(
            ProjectRow(
                id=f"proj-out-{os.getpid()}",
                name="out",
                org_id=other,
                owner_user_id="x",
            )
        )
        db.commit()
        proj_in = f"proj-in-{os.getpid()}"
        proj_out = f"proj-out-{os.getpid()}"
        assert runner_scope_allows_project(db, job_project_id=proj_in) is True
        assert (
            runner_scope_allows_project(
                db, project_ids=(proj_in,), job_project_id=proj_in
            )
            is True
        )
        assert (
            runner_scope_allows_project(
                db, project_ids=(proj_in,), job_project_id=proj_out
            )
            is False
        )
        assert (
            runner_scope_allows_project(
                db, org_id=oid, job_project_id=proj_in
            )
            is True
        )
        assert (
            runner_scope_allows_project(
                db, org_id=oid, job_project_id=proj_out
            )
            is False
        )
        assert (
            runner_scope_allows_project(
                db, project_ids=(proj_in,), job_project_id=""
            )
            is False
        )


def test_runner_token_scope_blocks_cross_project_claim(client: TestClient):
    admin_tok = {"X-API-Token": "admin-ops-token"}
    ah = _admin_headers(client)

    # org + two projects
    org = client.post(
        "/api/v1/orgs",
        headers=ah,
        json={"id": "org-run", "name": "RunOrg"},
    )
    assert org.status_code == 200
    p_ok = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-run"},
        json={"id": "p-ok", "name": "OK", "org_id": "org-run"},
    )
    assert p_ok.status_code == 200
    p_other = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-run"},
        json={"id": "p-other", "name": "Other", "org_id": "org-run"},
    )
    assert p_other.status_code == 200

    rid = "scoped-runner"
    client.post(
        "/api/v1/runners/register",
        headers=admin_tok,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["web"]},
    )
    tok = client.post(
        f"/api/v1/runners/{rid}/token",
        headers=ah,
        json={"org_id": "org-run", "project_ids": ["p-ok"]},
    ).json()
    assert tok["org_id"] == "org-run"
    assert tok["project_ids"] == ["p-ok"]
    runner_h = {"X-API-Token": tok["api_token"]}

    client.post(
        "/api/v1/runners/heartbeat",
        headers=runner_h,
        json={"runner_id": rid, "inventory": [], "devices": [], "capabilities": ["web"]},
    )

    # 越权项目任务
    j_bad = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "bad",
            "project_dir": "/tmp/p",
            "platform": "web",
            "project_id": "p-other",
            "preferred_runner_id": rid,
        },
    )
    assert j_bad.status_code == 200
    # 允许项目任务
    j_ok = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "ok",
            "project_dir": "/tmp/p",
            "platform": "web",
            "project_id": "p-ok",
            "preferred_runner_id": rid,
        },
    ).json()

    claimed = client.post(
        f"/api/v1/jobs/claim?runner_id={rid}", headers=runner_h
    ).json()
    assert claimed is not None
    assert claimed["id"] == j_ok["id"]
    assert claimed["project_id"] == "p-ok"

    # 越权任务仍 pending
    st = client.get(f"/api/v1/jobs/{j_bad.json()['id']}", headers=ah).json()
    assert st["status"] == "pending"


def test_patch_runner_scope_and_device_org_filter(client: TestClient):
    admin_tok = {"X-API-Token": "admin-ops-token"}
    ah = _admin_headers(client)

    client.post(
        "/api/v1/orgs",
        headers=ah,
        json={"id": "org-dev", "name": "DevOrg"},
    )
    # 建 operator 用户并加入组织
    created = client.post(
        "/api/v1/auth/users",
        headers={**ah, "X-Org-Id": "org-dev"},
        json={"username": "op1", "password": "Opuser12", "duty": "org_member"},
    )
    assert created.status_code == 200

    rid_a = "runner-org-a"
    rid_b = "runner-org-b"
    for rid in (rid_a, rid_b):
        client.post(
            "/api/v1/runners/register",
            headers=admin_tok,
            json={"runner_id": rid, "hostname": rid, "capabilities": ["android"]},
        )
    client.patch(
        f"/api/v1/runners/{rid_a}/scope",
        headers=ah,
        json={"org_id": "org-dev", "project_ids": []},
    )
    client.patch(
        f"/api/v1/runners/{rid_b}/scope",
        headers=ah,
        json={"org_id": "org-other", "project_ids": []},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=admin_tok,
        json={
            "runner_id": rid_a,
            "inventory": [{"udid": "u-a", "platform": "android", "name": "A"}], "devices": [{"udid": "u-a", "platform": "android", "name": "A"}],
        },
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=admin_tok,
        json={
            "runner_id": rid_b,
            "inventory": [{"udid": "u-b", "platform": "android", "name": "B"}], "devices": [{"udid": "u-b", "platform": "android", "name": "B"}],
        },
    )

    # admin 看全部
    all_devs = page_items(client.get("/api/v1/devices", headers=ah).json())
    udids_admin = {d["udid"] for d in all_devs}
    assert "u-a" in udids_admin and "u-b" in udids_admin

    login_op = client.post(
        "/api/v1/auth/login", json={"username": "op1", "password": "Opuser12"}
    ).json()
    oh = {
        "Authorization": f"Bearer {login_op['access_token']}",
        "X-Org-Id": "org-dev",
    }
    filtered = page_items(client.get("/api/v1/devices", headers=oh).json())
    udids_op = {d["udid"] for d in filtered}
    assert "u-a" in udids_op
    assert "u-b" not in udids_op
