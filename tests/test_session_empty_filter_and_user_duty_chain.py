"""本会话两类改动的白盒链路：空列表切筛选不闪 + 注册账号只走 duty。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FE = ROOT / "autopilot_platform" / "frontend" / "src"
PAGED = FE / "composables" / "usePagedList.ts"
PAGER = FE / "components" / "common" / "DataPager.vue"
DEVICE_FILTERS = FE / "composables" / "useDeviceBoardFilters.ts"
DEVICES_PANEL = FE / "components" / "DevicesPanel.vue"
USERS_PANEL = FE / "components" / "UsersPanel.vue"
ACTIONS = FE / "composables" / "mcAdminActions.ts"
ROLE_LABELS = FE / "components" / "projects" / "roleLabels.ts"

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items
from user_create_helpers import user_create_body

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.artifacts.users_artifacts import expand_create_duty
from autopilot_platform.platform.core import api_messages as msg
from autopilot_platform.platform.core.db import reset_engine


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def should_skip_empty_filter_reload(*, has_loaded: bool, universe_empty: bool) -> bool:
    """与 usePagedList.skipEmptyFilterReload 同一条判定。"""
    return has_loaded and universe_empty


def test_empty_filter_state_machine_contract():
    """全量为空时切筛选跳过 reload；换项目始终 reload。"""
    cases = [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ]
    for has_loaded, universe_empty, expect_skip in cases:
        assert (
            should_skip_empty_filter_reload(
                has_loaded=has_loaded, universe_empty=universe_empty
            )
            is expect_skip
        )

    src = _src(PAGED)
    assert "function skipEmptyFilterReload()" in src
    assert "return hasLoaded.value && universeEmpty.value;" in src
    assert "if (skipEmptyFilterReload()) return;" in src
    assert "universeEmpty.value = false;" in src
    assert "void reload(true);" in src
    assert "filterSources" in src
    assert "resetSources" in src
    assert "isUnfiltered" in src


def test_empty_filter_ui_chain_keeps_empty_state():
    """空状态跟 hasLoaded，分页条只在多于一页时出现，设备筛选走 skip。"""
    assert "mode === 'page' && multiPage" in _src(PAGER)
    assert "total > 0 || loading" not in _src(PAGER)

    devices = _src(DEVICES_PANEL)
    assert 'v-if="!items.length && hasLoaded"' in devices
    assert 'v-if="!items.length && !loading"' not in devices

    filters = _src(DEVICE_FILTERS)
    assert "skipEmptyFilterReload" in filters
    assert "filterSources: [busyFilter, platformFilter]" in filters
    assert "isUnfiltered:" in filters
    assert "listDevicesPage(undefined" in filters

    jobs = _src(FE / "components" / "JobsPanel.vue")
    assert "filterSources: [statusFilter]" in jobs
    assert "isUnfiltered:" in jobs
    assert 'v-if="!items.length && hasLoaded"' in jobs

    reports = _src(FE / "components" / "ReportsPanel.vue")
    assert "filterSources:" in reports
    assert "isUnfiltered:" in reports
    assert 'v-if="!items.length && hasLoaded"' in reports

    builds = _src(FE / "components" / "AppBuildsPanel.vue")
    assert "filterSources: [platformFilter]" in builds
    assert 'v-if="!filteredBuilds.length && hasLoaded"' in builds


def test_role_labels_are_not_all_called_admin():
    text = _src(ROLE_LABELS)
    assert 'admin: "系统管理员"' in text
    assert 'operator: "普通用户"' in text
    assert 'admin: "组织管理员"' in text
    assert 'owner: "组织负责人"' in text
    assert 'owner: "项目负责人"' in text
    assert "系统管理员" != "组织管理员"
    assert "组织管理员" != "项目负责人"


def test_frontend_create_user_posts_duty_only():
    """UI 选项 → onCreateUser 只 POST duty（+ 项目时的 project_id），不再发 role。"""
    panel = _src(USERS_PANEL)
    assert "dutyOptions" in panel
    assert "这个人来干什么" in panel
    for duty in (
        "user",
        "sys_admin",
        "org_member",
        "org_admin",
        "project_member",
        "project_owner",
        "project_viewer",
    ):
        assert duty in panel
    assert "onCreateUser" in panel

    actions = _src(ACTIONS)
    assert re.search(r"duty,", actions) or 'duty,' in actions
    assert "body.project_id = projectId" in actions
    assert "role:" not in actions.split("const body")[1].split("try {")[0]
    assert "org_role" not in actions
    assert "project_role" not in actions
    assert '"/api/v1/auth/users"' in actions


def test_expand_create_duty_mapping():
    assert expand_create_duty("user") == ("operator", "", "", "")
    assert expand_create_duty("sys_admin") == ("admin", "", "", "")
    assert expand_create_duty("sys_admin", org_id="o1") == ("admin", "member", "", "")
    assert expand_create_duty("org_member", org_id="o1") == ("operator", "member", "", "")
    assert expand_create_duty("org_admin", org_id="o1") == ("operator", "admin", "", "")
    assert expand_create_duty("project_member", project_id="p1") == (
        "operator",
        "member",
        "p1",
        "member",
    )
    assert expand_create_duty("project_owner", project_id="p1") == (
        "operator",
        "member",
        "p1",
        "owner",
    )
    assert expand_create_duty("project_viewer", project_id="p1") == (
        "operator",
        "member",
        "p1",
        "viewer",
    )
    with pytest.raises(ValueError, match=re.escape(msg.USER_CREATE_ORG_REQUIRED)):
        expand_create_duty("org_member")
    with pytest.raises(ValueError, match=re.escape(msg.USER_CREATE_PROJECT_REQUIRED)):
        expand_create_duty("project_owner")
    with pytest.raises(ValueError, match=re.escape(msg.USER_CREATE_DUTY_INVALID)):
        expand_create_duty("operator")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_test.db"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _login(client: TestClient, user="admin", password="admin") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_duty_user_does_not_join_org(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "d-user", "name": "U"}).status_code == 200
    h = {**ah, "X-Org-Id": "d-user"}
    r = client.post(
        "/api/v1/auth/users",
        headers=h,
        json=user_create_body("plain1", "Plain123", duty="user"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"
    names = {m["username"] for m in page_items(client.get("/api/v1/orgs/d-user/members", headers=h).json())}
    assert "plain1" not in names


def test_duty_sys_admin_and_org_admin_are_different(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "d-sa", "name": "SA"}).status_code == 200
    h = {**ah, "X-Org-Id": "d-sa"}
    r = client.post(
        "/api/v1/auth/users",
        headers=h,
        json=user_create_body("sys1", "Sysuser12", duty="sys_admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    r = client.post(
        "/api/v1/auth/users",
        headers=h,
        json=user_create_body("oadm1", "Oadm1234", duty="org_admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"
    members = {m["username"]: m["role"] for m in page_items(client.get("/api/v1/orgs/d-sa/members", headers=h).json())}
    assert members["sys1"] == "member"
    assert members["oadm1"] == "admin"


def test_org_admin_cannot_create_sys_admin(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "d-deny", "name": "D"}).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json=user_create_body("orgmgr", "OrgMgr12", duty="user"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/d-deny/members",
            headers=ah,
            json={"username": "orgmgr", "role": "admin"},
        ).status_code
        == 200
    )
    mh = {**_login(client, "orgmgr", "OrgMgr12"), "X-Org-Id": "d-deny"}
    r = client.post(
        "/api/v1/auth/users",
        headers=mh,
        json=user_create_body("hacker", "Hacker12", duty="sys_admin"),
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/auth/users",
        headers=mh,
        json=user_create_body("newbie", "Newbie12", duty="org_member"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"


def test_duty_project_roles_one_transaction(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "d-p", "name": "P"}).status_code == 200
    h = {**ah, "X-Org-Id": "d-p"}
    assert (
        client.post(
            "/api/v1/projects",
            headers=h,
            json={"id": "p-duty", "name": "Duty", "org_id": "d-p"},
        ).status_code
        == 200
    )

    for uname, duty, want_org, want_proj in (
        ("lead1", "project_owner", "member", "owner"),
        ("mem1", "project_member", "member", "member"),
        ("view1", "project_viewer", "member", "viewer"),
    ):
        r = client.post(
            "/api/v1/auth/users",
            headers=h,
            json=user_create_body(uname, f"{uname}Pass1", duty=duty, project_id="p-duty"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "operator"
        org = next(
            m
            for m in page_items(client.get("/api/v1/orgs/d-p/members", headers=h).json())
            if m["username"] == uname
        )
        assert org["role"] == want_org
        proj = next(
            m
            for m in page_items(client.get("/api/v1/projects/p-duty/members", headers=h).json())
            if m["username"] == uname
        )
        assert proj["role"] == want_proj

    bad = client.post(
        "/api/v1/auth/users",
        headers=h,
        json=user_create_body("ghost1", "Ghostuser1", duty="project_member", project_id="no-such"),
    )
    assert bad.status_code in (400, 404, 409)
    names = {u["username"] for u in page_items(client.get("/api/v1/auth/users", headers=ah).json())}
    assert "ghost1" not in names

    missing = client.post(
        "/api/v1/auth/users",
        headers=h,
        json=user_create_body("noproj", "Noproj12", duty="project_owner"),
    )
    assert missing.status_code == 400
