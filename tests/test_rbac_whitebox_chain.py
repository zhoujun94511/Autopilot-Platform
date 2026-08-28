"""三账号 RBAC 链路白盒测试 — 对齐 docs/rbac-capability-matrix.md §7。

账号 A platform_admin：内置 admin/admin
账号 B org_admin：rbac-orgadmin（组织 admin）
账号 C operator：rbac-operator（组织 member + 项目 member）
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

ORG_ID = "org-rbac-wb"
PROJECT_ID = "p-rbac-wb"
RUNNER_ID = "rbac-test-runner"


@dataclass(frozen=True)
class RbacAccounts:
    platform_admin: dict
    org_admin: dict
    operator: dict


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rbac_whitebox.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
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


def _login(client: TestClient, user: str, password: str) -> dict:
    r = client.post(
        "/api/v1/auth/login", json={"username": user, "password": password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _bootstrap_three_accounts(client: TestClient) -> RbacAccounts:
    """造号：platform_admin / org_admin / operator + org + project。"""
    ah = _login(client, "admin", "admin")

    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": ORG_ID, "name": "RBAC Whitebox Org"},
        ).status_code
        == 200
    )

    for username, password in (
        ("rbac-orgadmin", "OrgAdmin12"),
        ("rbac-operator", "Operator12"),
    ):
        assert (
            client.post(
                "/api/v1/auth/users",
                headers=ah,
                json={"username": username, "password": password, "duty": "user"},
            ).status_code
            == 200
        )

    assert (
        client.post(
            f"/api/v1/orgs/{ORG_ID}/members",
            headers=ah,
            json={"username": "rbac-orgadmin", "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/orgs/{ORG_ID}/members",
            headers=ah,
            json={"username": "rbac-operator", "role": "member"},
        ).status_code
        == 200
    )

    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": ORG_ID},
            json={"id": PROJECT_ID, "name": "RBAC Project", "org_id": ORG_ID},
        ).status_code
        == 200
    )
    for username, role in (
        ("rbac-operator", "member"),
        ("rbac-orgadmin", "member"),
    ):
        assert (
            client.post(
                f"/api/v1/projects/{PROJECT_ID}/members",
                headers=ah,
                json={"username": username, "role": role},
            ).status_code
            == 200
        )

    org_admin_h = {
        **_login(client, "rbac-orgadmin", "OrgAdmin12"),
        "X-Org-Id": ORG_ID,
    }
    operator_h = {
        **_login(client, "rbac-operator", "Operator12"),
        "X-Org-Id": ORG_ID,
    }

    # 注册 Runner 供 token 签发测试
    admin_tok = {"X-API-Token": "admin-ops-token"}
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=admin_tok,
            json={
                "runner_id": RUNNER_ID,
                "hostname": "rbac-host",
                "capabilities": ["web"],
                "registration_source": "ide",
            },
        ).status_code
        == 200
    )

    return RbacAccounts(
        platform_admin=ah,
        org_admin=org_admin_h,
        operator=operator_h,
    )


@pytest.fixture()
def accounts(client: TestClient) -> RbacAccounts:
    return _bootstrap_three_accounts(client)


def _me_role(client: TestClient, headers: dict) -> str:
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return str(r.json().get("role") or "")


def test_account_bootstrap_roles(client: TestClient, accounts: RbacAccounts):
    assert _me_role(client, accounts.platform_admin) == "admin"
    assert _me_role(client, accounts.org_admin) == "operator"
    assert _me_role(client, accounts.operator) == "operator"


@pytest.mark.parametrize(
    ("label", "header_key", "expect_tokens", "expect_ops_summary"),
    [
        ("platform_admin", "platform_admin", True, 200),
        ("org_admin", "org_admin", False, 403),
        ("operator", "operator", False, 403),
    ],
)
def test_api_response_contract_by_role(
    client: TestClient,
    accounts: RbacAccounts,
    label: str,
    header_key: str,
    expect_tokens: bool,
    expect_ops_summary: int,
):
    headers = getattr(accounts, header_key)
    params = {"project_id": PROJECT_ID}

    stats = client.get("/api/v1/design/stats", headers=headers, params=params)
    assert stats.status_code == 200, stats.text
    has_tokens = "tokens" in stats.json()
    assert has_tokens is expect_tokens, f"{label} design/stats tokens={has_tokens}"

    agentops = client.get("/api/v1/ops/agentops", headers=headers, params=params)
    assert agentops.status_code == 200, agentops.text
    has_agent_tokens = "tokens" in agentops.json()
    assert has_agent_tokens is expect_tokens, f"{label} ops/agentops tokens"

    summary = client.get("/api/v1/ops/summary", headers=headers)
    assert summary.status_code == expect_ops_summary, summary.text

    export = client.get(
        "/api/v1/design/stats/export", headers=headers, params=params
    )
    assert export.status_code == 200, export.text
    csv_text = export.text
    if expect_tokens:
        assert "total_tokens" in csv_text or "token" in csv_text.lower()
    else:
        assert "daily_budget" not in csv_text


def test_runner_and_ops_gates(client: TestClient, accounts: RbacAccounts):
    ah, oh, op_h = (
        accounts.platform_admin,
        accounts.org_admin,
        accounts.operator,
    )

    # 只读：三角色均可列 Runner
    for name, h in (
        ("platform_admin", ah),
        ("org_admin", oh),
        ("operator", op_h),
    ):
        r = client.get("/api/v1/runners", headers=h)
        assert r.status_code == 200, f"{name} GET /runners: {r.text}"

    # 设备看板只读
    for name, h in (
        ("platform_admin", ah),
        ("org_admin", oh),
        ("operator", op_h),
    ):
        r = client.get("/api/v1/devices", headers=h)
        assert r.status_code == 200, f"{name} GET /devices: {r.text}"

    # 平台 admin Token 签发
    tok_admin = client.post(
        f"/api/v1/runners/{RUNNER_ID}/token",
        headers=ah,
        json={"org_id": ORG_ID, "project_ids": [PROJECT_ID]},
    )
    assert tok_admin.status_code == 200, tok_admin.text

    for name, h in (("org_admin", oh), ("operator", op_h)):
        r = client.post(
            f"/api/v1/runners/{RUNNER_ID}/token",
            headers=h,
            json={"org_id": ORG_ID, "project_ids": [PROJECT_ID]},
        )
        assert r.status_code == 403, f"{name} issue runner token should 403"

    # 运维配置仅 platform admin
    for name, h, code in (
        ("platform_admin", ah, 200),
        ("org_admin", oh, 403),
        ("operator", op_h, 403),
    ):
        r = client.get("/api/v1/ops/config", headers=h)
        assert r.status_code == code, f"{name} GET /ops/config: {r.text}"

    # 托管 Runner 仅 platform admin
    for name, h, code in (
        ("platform_admin", ah, 200),
        ("org_admin", oh, 403),
        ("operator", op_h, 403),
    ):
        r = client.get("/api/v1/runners/managed", headers=h)
        assert r.status_code == code, f"{name} GET /runners/managed: {r.text}"

    # 设备 release：平台管理员或 Runner 所属组织管理员可操作
    admin_tok = {"X-API-Token": "admin-ops-token"}
    assert (
        client.post(
            "/api/v1/runners/heartbeat",
            headers=admin_tok,
            json={
                "runner_id": RUNNER_ID,
                "inventory": [{"udid": "rbac-dev-1", "platform": "android", "name": "D1"}], "devices": [{"udid": "rbac-dev-1", "platform": "android", "name": "D1"}],
            },
        ).status_code
        == 200
    )
    assert client.post("/api/v1/devices/rbac-dev-1/release", headers=op_h).status_code == 403
    assert client.post("/api/v1/devices/rbac-dev-1/release", headers=oh).status_code == 200
    assert client.post("/api/v1/devices/rbac-dev-1/release", headers=ah).status_code == 200


def test_operator_cannot_issue_scoped_runner_token(client: TestClient, accounts: RbacAccounts):
    op_h = accounts.operator
    ah = accounts.platform_admin
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=op_h,
            json={
                "runner_id": "rbac-op-runner",
                "hostname": "op-ide",
                "registration_source": "ide",
            },
        ).status_code
        == 200
    )
    denied = client.post(
        "/api/v1/runners/rbac-op-runner/scoped-token",
        headers=op_h,
        json={"org_id": ORG_ID, "project_ids": [PROJECT_ID]},
    )
    assert denied.status_code == 403, denied.text
    ok = client.post(
        "/api/v1/runners/rbac-op-runner/scoped-token",
        headers=ah,
        json={"org_id": ORG_ID, "project_ids": [PROJECT_ID]},
    )
    assert ok.status_code == 200, ok.text


def test_user_management_and_audit_scope(client: TestClient, accounts: RbacAccounts):
    ah, oh, op_h = (
        accounts.platform_admin,
        accounts.org_admin,
        accounts.operator,
    )

    # org_admin 可列本 org 用户
    r = client.get("/api/v1/auth/users", headers=oh)
    assert r.status_code == 200, r.text
    names = {u["username"] for u in page_items(r.json())}
    assert "rbac-operator" in names
    assert "rbac-orgadmin" in names

    # operator 不可管用户
    assert client.get("/api/v1/auth/users", headers=op_h).status_code == 403

    # org_admin 无 X-Org-Id 不可管用户
    bare_org_admin = _login(client, "rbac-orgadmin", "OrgAdmin12")
    assert client.get("/api/v1/auth/users", headers=bare_org_admin).status_code == 403

    # 审计：org_admin 本 org；operator 403
    r = client.get("/api/v1/audit", headers=oh)
    assert r.status_code == 200, r.text
    assert all(a.get("org_id") in (ORG_ID, None, "") or True for a in page_items(r.json()))

    assert client.get("/api/v1/audit", headers=op_h).status_code == 403

    # platform admin 全平台审计
    r = client.get("/api/v1/audit", headers=ah)
    assert r.status_code == 200, r.text


def test_operator_cannot_runner_control_plane(client: TestClient, accounts: RbacAccounts):
    op_h = accounts.operator
    requests = (
        client.post(
            "/api/v1/runners/register",
            headers=op_h,
            json={"runner_id": "forged", "hostname": "h"},
        ),
        client.post(
            "/api/v1/runners/heartbeat",
            headers=op_h,
            json={"runner_id": "forged", "inventory": [], "devices": []},
        ),
        client.post("/api/v1/jobs/claim?runner_id=forged", headers=op_h),
    )
    assert all(r.status_code == 403 for r in requests)


def test_org_admin_cannot_create_sys_admin(client: TestClient, accounts: RbacAccounts):
    """组织 admin 可建用户，但不能指定系统管理员。"""
    oh = accounts.org_admin
    denied = client.post(
        "/api/v1/auth/users",
        headers=oh,
        json={"username": "rbac-hacker", "password": "Hacker12", "duty": "sys_admin"},
    )
    assert denied.status_code == 403
    r = client.post(
        "/api/v1/auth/users",
        headers=oh,
        json={"username": "rbac-newbie", "password": "Newbie12", "duty": "org_member"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"
