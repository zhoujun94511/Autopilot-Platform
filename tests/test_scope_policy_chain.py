"""ScopePolicy 白盒链：资源池并集/收窄、ACL 不依赖顶栏项目、设备可见性、AI 落库 vs codegen。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}
FE = Path(ROOT) / "autopilot_platform" / "frontend" / "src"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "scope_chain.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _login(client: TestClient, user="admin", password="admin") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_user(client: TestClient, ah: dict, username: str, password: str) -> None:
    r = client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": username, "password": password, "duty": "user"},
    )
    assert r.status_code == 200, r.text


def _seed_org_project(
    client: TestClient,
    ah: dict,
    *,
    org_id: str,
    project_id: str,
    owner: str | None = None,
) -> None:
    existed = client.get(f"/api/v1/orgs/{org_id}", headers=ah)
    if existed.status_code != 200:
        assert (
            client.post(
                "/api/v1/orgs",
                headers=ah,
                json={"id": org_id, "name": org_id},
            ).status_code
            == 200
        )
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": org_id},
        json={"id": project_id, "name": project_id, "org_id": org_id},
    )
    assert r.status_code == 200, r.text
    if owner and owner != "admin":
        assert (
            client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=ah,
                json={"username": owner, "role": "owner"},
            ).status_code
            == 200
        )


def _register_runner(client: TestClient, runner_id: str, *, org_id: str, udid: str) -> str:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "hostname": runner_id,
                "capabilities": ["android"],
            },
        ).status_code
        == 200
    )
    admin = _login(client)
    assert (
        client.patch(
            f"/api/v1/runners/{runner_id}/scope",
            headers=admin,
            json={"org_id": org_id, "project_ids": []},
        ).status_code
        == 200
    )
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "inventory": [
                {
                    "udid": udid,
                    "platform": "android",
                    "name": udid,
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ], "devices": [
                {
                    "udid": udid,
                    "platform": "android",
                    "name": udid,
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ],
        },
    )
    assert hb.status_code == 200, hb.text
    devices = page_items(client.get("/api/v1/devices", headers=admin).json())
    hit = next(
        (d for d in devices if d.get("udid") == udid and d.get("runner_id") == runner_id),
        None,
    )
    assert hit is not None, devices
    device_id = str(hit.get("id") or "")
    assert device_id
    return device_id


def _enable_ai(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()


def test_org_admin_lists_all_pools_without_project_filter(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "alice", "Alice123")
    _seed_org_project(client, ah, org_id="org-pool", project_id="proj-a", owner="alice")
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "org-pool"},
            json={"id": "proj-b", "name": "proj-b", "org_id": "org-pool"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-pool/members",
            headers=ah,
            json={"username": "alice", "role": "admin"},
        ).status_code
        == 200
    )
    alice = _login(client, "alice", "Alice123")
    pool_open = client.post(
        "/api/v1/orgs/org-pool/resource-pools",
        headers={**alice, "X-Org-Id": "org-pool"},
        json={"name": "unassigned"},
    )
    assert pool_open.status_code == 201, pool_open.text
    pool_a = client.post(
        "/api/v1/orgs/org-pool/resource-pools",
        headers={**alice, "X-Org-Id": "org-pool"},
        json={"name": "lab-a"},
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_a}/projects",
            headers={**alice, "X-Org-Id": "org-pool"},
            json={"project_id": "proj-a"},
        ).status_code
        == 200
    )
    listed = client.get(
        "/api/v1/orgs/org-pool/resource-pools",
        headers={**alice, "X-Org-Id": "org-pool"},
    )
    assert listed.status_code == 200, listed.text
    names = {item["name"] for item in page_items(listed.json())}
    assert names == {"unassigned", "lab-a"}


def test_member_pool_union_then_project_narrow(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "member1", "Member123")
    _seed_org_project(client, ah, org_id="org-m", project_id="proj-a")
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-m"},
        json={"id": "proj-b", "name": "proj-b", "org_id": "org-m"},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/v1/orgs/org-m/members",
            headers=ah,
            json={"username": "member1", "role": "member"},
        ).status_code
        == 200
    )
    for pid in ("proj-a", "proj-b"):
        assert (
            client.post(
                f"/api/v1/projects/{pid}/members",
                headers=ah,
                json={"username": "member1", "role": "member"},
            ).status_code
            == 200
        )
    pool_a = client.post(
        "/api/v1/orgs/org-m/resource-pools",
        headers={**ah, "X-Org-Id": "org-m"},
        json={"name": "pool-a"},
    ).json()["id"]
    pool_b = client.post(
        "/api/v1/orgs/org-m/resource-pools",
        headers={**ah, "X-Org-Id": "org-m"},
        json={"name": "pool-b"},
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_a}/projects",
            headers={**ah, "X-Org-Id": "org-m"},
            json={"project_id": "proj-a"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_b}/projects",
            headers={**ah, "X-Org-Id": "org-m"},
            json={"project_id": "proj-b"},
        ).status_code
        == 200
    )
    member = _login(client, "member1", "Member123")
    union = client.get("/api/v1/orgs/org-m/resource-pools", headers=member)
    assert union.status_code == 200, union.text
    union_ids = {item["id"] for item in page_items(union.json())}
    assert union_ids == {pool_a, pool_b}

    only_a = client.get(
        "/api/v1/orgs/org-m/resource-pools?project_id=proj-a",
        headers=member,
    )
    assert only_a.status_code == 200, only_a.text
    assert {item["id"] for item in page_items(only_a.json())} == {pool_a}


def test_member_devices_union_then_project_narrow(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "member1", "Member123")
    _seed_org_project(client, ah, org_id="org-d", project_id="proj-a")
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "org-d"},
            json={"id": "proj-b", "name": "proj-b", "org_id": "org-d"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-d/members",
            headers=ah,
            json={"username": "member1", "role": "member"},
        ).status_code
        == 200
    )
    for pid in ("proj-a", "proj-b"):
        assert (
            client.post(
                f"/api/v1/projects/{pid}/members",
                headers=ah,
                json={"username": "member1", "role": "member"},
            ).status_code
            == 200
        )
    dev_a = _register_runner(client, "runner-a", org_id="org-d", udid="udid-a")
    dev_b = _register_runner(client, "runner-b", org_id="org-d", udid="udid-b")
    pool_a = client.post(
        "/api/v1/orgs/org-d/resource-pools",
        headers={**ah, "X-Org-Id": "org-d"},
        json={"name": "pool-a"},
    ).json()["id"]
    pool_b = client.post(
        "/api/v1/orgs/org-d/resource-pools",
        headers={**ah, "X-Org-Id": "org-d"},
        json={"name": "pool-b"},
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_a}/runners",
            headers=ah,
            json={"resource_id": "runner-a"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_b}/runners",
            headers=ah,
            json={"resource_id": "runner-b"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_a}/projects",
            headers=ah,
            json={"project_id": "proj-a"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_b}/projects",
            headers=ah,
            json={"project_id": "proj-b"},
        ).status_code
        == 200
    )
    member = _login(client, "member1", "Member123")
    union = page_items(client.get("/api/v1/devices", headers=member).json())
    union_ids = {d["id"] for d in union}
    assert dev_a in union_ids and dev_b in union_ids

    only_a = page_items(
        client.get("/api/v1/devices?project_id=proj-a", headers=member).json()
    )
    only_ids = {d["id"] for d in only_a}
    assert only_ids == {dev_a}


def test_acl_list_does_not_need_request_project_header(client: TestClient):
    import io
    import zipfile

    ah = _login(client)
    _create_user(client, ah, "alice", "alice123")
    _create_user(client, ah, "bob", "bob12345")
    _seed_org_project(client, ah, org_id="org-acl", project_id="alice-art", owner="alice")
    assert (
        client.post(
            "/api/v1/orgs/org-acl/members",
            headers=ah,
            json={"username": "bob", "role": "member"},
        ).status_code
        == 200
    )
    alice_h = _login(client, "alice", "alice123")
    bob_h = _login(client, "bob", "bob12345")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.txt", "1")
    r = client.post(
        "/api/v1/artifacts",
        headers=alice_h,
        files={"file": ("p.zip", buf.getvalue(), "application/zip")},
        data={"name": "private", "project_id": "alice-art"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    granted = client.post(
        "/api/v1/acl",
        headers=alice_h,
        json={
            "resource_type": "artifact",
            "resource_id": aid,
            "username": "bob",
            "permission": "read",
        },
    )
    assert granted.status_code == 200, granted.text
    listed = client.get(
        "/api/v1/acl",
        headers=bob_h,
        params={"resource_type": "artifact", "resource_id": aid},
    )
    assert listed.status_code == 200, listed.text
    items = page_items(listed.json())
    assert any(str(x.get("resource_id")) == aid for x in items)


def test_generate_logical_cases_requires_project_id(client: TestClient):
    h = _login(client)
    missing = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=h,
        json={"requirement_text": "打开设置", "max_cases": 1},
    )
    assert missing.status_code == 422, missing.text
    empty = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=h,
        json={"project_id": "", "requirement_text": "打开设置", "max_cases": 1},
    )
    assert empty.status_code == 400, empty.text
    assert "project_id" in (empty.text or "").lower() or "需要" in empty.text


def test_codegen_empty_project_uses_authoring_bucket(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)
    captured = {}

    def fake_chat(_messages, **_kwargs):
        from autopilot_platform.platform.ai import ai_usage

        captured["scope"] = ai_usage.get_ai_billing_scope()
        return '{"name":"t","steps":[]}'

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers=h,
        json={"prompt": "打开设置", "purpose": "authoring", "project_id": ""},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("project_id") == "__authoring__"
    scope = captured.get("scope") or {}
    assert scope.get("project_id") == "__authoring__"


def test_job_artifact_schedule_require_project_id(client: TestClient):
    h = _login(client)
    job = client.post(
        "/api/v1/jobs",
        headers=h,
        json={"name": "no-pid", "project_dir": "/tmp/suite", "platform": "android"},
    )
    assert job.status_code == 403, job.text

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.txt", "1")
    art = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("p.zip", buf.getvalue(), "application/zip")},
        data={"name": "no-pid", "project_id": ""},
    )
    assert art.status_code == 403, art.text

    sched = client.post(
        "/api/v1/schedules",
        headers=h,
        json={
            "name": "no-pid",
            "project_dir": "/tmp/suite",
            "platform": "android",
            "project_id": "",
        },
    )
    assert sched.status_code == 403, sched.text


def test_device_board_without_project_keeps_org_devices(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "member1", "Member123")
    _seed_org_project(client, ah, org_id="org-board", project_id="proj-a")
    assert (
        client.post(
            "/api/v1/orgs/org-board/members",
            headers=ah,
            json={"username": "member1", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/proj-a/members",
            headers=ah,
            json={"username": "member1", "role": "member"},
        ).status_code
        == 200
    )
    _register_runner(client, "runner-board", org_id="org-board", udid="udid-board")
    member = _login(client, "member1", "Member123")
    board = client.get("/api/v1/devices/board", headers=member)
    assert board.status_code == 200, board.text
    devices = board.json().get("devices") or []
    assert any(d.get("udid") == "udid-board" for d in devices)
    summary = client.get("/api/v1/devices/board?summary_only=true", headers=member)
    assert summary.status_code == 200, summary.text
    assert int((summary.json().get("summary") or {}).get("online") or 0) >= 1


def test_design_review_requires_project_write(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "viewer1", "Viewer123")
    _seed_org_project(client, ah, org_id="org-rev", project_id="proj-rev")
    assert (
        client.post(
            "/api/v1/orgs/org-rev/members",
            headers=ah,
            json={"username": "viewer1", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/proj-rev/members",
            headers=ah,
            json={"username": "viewer1", "role": "viewer"},
        ).status_code
        == 200
    )
    created = client.post(
        "/api/v1/design/logical-cases",
        headers=ah,
        json={
            "project_id": "proj-rev",
            "title": "审核门禁",
            "logical_steps": ["打开"],
            "expected_results": ["可见"],
            "review_status": "AI_DRAFT",
        },
    )
    assert created.status_code == 200, created.text
    cid = created.json()["logical_case_id"]
    viewer = _login(client, "viewer1", "Viewer123")
    denied = client.patch(
        f"/api/v1/design/logical-cases/{cid}",
        headers=viewer,
        json={"review_status": "APPROVED"},
    )
    assert denied.status_code == 403, denied.text
    rag = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=ah,
        json={
            "project_id": "",
            "requirement_text": "打开设置",
            "max_cases": 1,
            "use_rag": True,
        },
    )
    assert rag.status_code == 400, rag.text


def test_frontend_scope_policy_wiring():
    filters = (FE / "composables" / "useDeviceBoardFilters.ts").read_text(encoding="utf-8")
    assert "listDevicesPage(undefined" in filters
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "fetchAllDevices(undefined)" in actions
    assert "pid ? fetchAllDevices(pid)" in actions
    assert "dispatchDevices.value = dispatch ?? all" in actions
    job = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert ':devices="dispatchDevices"' in job
    sched = (FE / "components" / "SchedulesPanel.vue").read_text(encoding="utf-8")
    assert ':devices="dispatchDevices"' in sched
    enqueue = (FE / "components" / "design" / "EnqueueRunConfigCard.vue").read_text(
        encoding="utf-8"
    )
    assert ':devices="dispatchDevices"' in enqueue
    caps = (FE / "composables" / "useCapabilities.ts").read_text(encoding="utf-8")
    assert "if (!pid) return Boolean(loggedIn.value);" in caps
    pools = (FE / "components" / "ResourcePoolsPanel.vue").read_text(encoding="utf-8")
    assert 'listResourcePoolsPage(orgId.value, "",' in pools
    share = (FE / "components" / "SharePanel.vue").read_text(encoding="utf-8")
    assert "建立或撤销共享需要该资源所属项目的写权限" in share
