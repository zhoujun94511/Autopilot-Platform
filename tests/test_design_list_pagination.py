"""设计域列表分页 / 筛选 API。"""

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

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

from list_page_helpers import page_items, page_total

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
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
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_requirements_list_compat_and_pagination(client: TestClient):
    h = _login(client)
    for i in range(25):
        r = client.post(
            "/api/v1/design/requirements",
            headers=h,
            json={
                "project_id": "p-page",
                "title": f"需求标题{i:02d}",
                "content": f"内容关键词 alpha-{i}",
                "req_key": f"REQ-{i:03d}",
                "priority": "high" if i % 2 == 0 else "low",
            },
        )
        assert r.status_code == 200, r.text

    # 无 page：兼容返回 list
    r = client.get("/api/v1/design/requirements?project_id=p-page", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 25

    # 带 page：分页对象
    r = client.get(
        "/api/v1/design/requirements?project_id=p-page&page=1&page_size=20",
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 25
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 20

    r = client.get(
        "/api/v1/design/requirements?project_id=p-page&page=2&page_size=20",
        headers=h,
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 5

    # 搜索
    r = client.get(
        "/api/v1/design/requirements?project_id=p-page&page=1&page_size=50&q=REQ-00",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all("REQ-00" in (it["req_key"] or "") or "00" in it["title"] for it in r.json()["items"])

    # 优先级筛选
    r = client.get(
        "/api/v1/design/requirements?project_id=p-page&page=1&page_size=100&priority=high",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["total"] == 13
    assert all(it["priority"] == "high" for it in r.json()["items"])

    # 批量删除
    ids = [it["id"] for it in r.json()["items"][:3]]
    r = client.post(
        "/api/v1/design/requirements/batch-delete",
        headers=h,
        json={"item_ids": ids},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 3


def test_knowledge_list_pagination_filters(client: TestClient):
    h = _login(client)
    for i in range(22):
        r = client.post(
            "/api/v1/design/knowledge",
            headers=h,
            json={
                "project_id": "p-kn",
                "title": f"知识{i:02d}",
                "content": f"规则 body-{i}",
                "category": "business_rules" if i % 2 == 0 else "other",
                "confirmed": i % 3 == 0,
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/design/knowledge?project_id=p-kn", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 22

    r = client.get(
        "/api/v1/design/knowledge?project_id=p-kn&page=1&page_size=20&category=business_rules",
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 11
    assert len(body["items"]) == 11
    assert all(it["category"] == "business_rules" for it in body["items"])

    r = client.get(
        "/api/v1/design/knowledge?project_id=p-kn&page=1&page_size=50&confirmed=true&q=知识0",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all(it["confirmed"] is True for it in r.json()["items"])


def test_documents_list_pagination(client: TestClient, tmp_path):
    h = _login(client)
    # 通过 import 接口写入多份文档
    for i in range(5):
        files = {"files": (f"spec-{i}.md", f"# Doc {i}\ncontent-{i}".encode("utf-8"), "text/markdown")}
        r = client.post(
            "/api/v1/design/documents/import",
            headers=h,
            data={
                "project_id": "p-docs-page",
                "auto_analyze": "false",
                "use_llm": "false",
                "analysis_type": "requirements",
                "max_requirements": "5",
            },
            files=files,
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/design/documents?project_id=p-docs-page", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 5

    r = client.get(
        "/api/v1/design/documents?project_id=p-docs-page&page=1&page_size=2&sort_by=filename&order=asc",
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    names = [it["filename"] for it in body["items"]]
    assert names == sorted(names)

    r = client.get(
        "/api/v1/design/documents?project_id=p-docs-page&page=1&page_size=20&q=spec-1",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1

    ids = [it["id"] for it in body["items"]]
    r = client.post(
        "/api/v1/design/documents/batch-delete",
        headers=h,
        json={"item_ids": ids},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 2


def test_logical_cases_list_compat_and_pagination(client: TestClient):
    h = _login(client)
    for i in range(25):
        r = client.post(
            "/api/v1/design/logical-cases",
            headers=h,
            json={
                "project_id": "p-cases-page",
                "title": f"用例标题{i:02d}",
                "logical_steps": [f"步骤 {i}"],
                "expected_results": ["预期"],
                "case_key": f"LC-{i:03d}",
                "automation_status": "PENDING_VERIFY" if i % 2 == 0 else "INTENT_READY",
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/design/logical-cases?project_id=p-cases-page", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 25

    r = client.get(
        "/api/v1/design/logical-cases?project_id=p-cases-page&page=1&page_size=20",
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 25
    assert body["page"] == 1
    assert len(body["items"]) == 20

    r = client.get(
        "/api/v1/design/logical-cases?project_id=p-cases-page&page=2&page_size=20",
        headers=h,
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 5

    r = client.get(
        "/api/v1/design/logical-cases?project_id=p-cases-page&page=1&page_size=50&automation_status=PENDING_VERIFY",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["total"] == 13
    assert all(it["automation_status"] == "PENDING_VERIFY" for it in r.json()["items"])


def test_schedules_and_users_list_pagination(client: TestClient):
    h = _login(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=h, json={"id": "org-sched-page", "name": "计划分页"}
        ).status_code
        == 200
    )
    h_org = {**h, "X-Org-Id": "org-sched-page"}
    assert (
        client.post(
            "/api/v1/projects",
            headers=h_org,
            json={"id": "proj-sched-page", "name": "计划分页项目", "org_id": "org-sched-page"},
        ).status_code
        == 200
    )
    for i in range(55):
        r = client.post(
            "/api/v1/schedules",
            headers=h,
            json={
                "name": f"plan-{i:02d}",
                "project_dir": f"/tmp/suite-{i}",
                "platform": "android",
                "project_id": "proj-sched-page",
                "delay_sec": 3600,
                "interval_sec": 0,
                "repeat": 1,
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/schedules?limit=50&offset=0", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) == 50

    r = client.get("/api/v1/schedules?limit=50&offset=50", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) == 5

    for i in range(3, 58):
        r = client.post(
            "/api/v1/auth/users",
            headers=h,
            json={"username": f"paguser{i}", "password": "Test1234!", "duty": "user"},
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/auth/users?limit=50&offset=0", headers=h)
    assert r.status_code == 200
    page1 = page_items(r.json())
    assert len(page1) == 50

    r = client.get("/api/v1/auth/users?limit=50&offset=50", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) >= 5


def test_projects_list_pagination(client: TestClient):
    h = _login(client)
    assert client.post(
        "/api/v1/orgs", headers=h, json={"id": "org-proj-page", "name": "分页项目组织"}
    ).status_code == 200
    for i in range(55):
        r = client.post(
            "/api/v1/projects",
            headers={**h, "X-Org-Id": "org-proj-page"},
            json={
                "id": f"proj-page-{i:02d}",
                "name": f"分页项目{i:02d}",
                "org_id": "org-proj-page",
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/projects?limit=50&offset=0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert page_total(body) >= 55
    assert len(page_items(body)) == 50

    r = client.get("/api/v1/projects?limit=50&offset=50", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) >= 5

    r = client.get("/api/v1/projects?page=2&page_size=50", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 2
    assert len(page_items(body)) >= 5

    r = client.get("/api/v1/projects?q=proj-page-01", headers=h)
    assert r.status_code == 200
    hits = page_items(r.json())
    assert len(hits) >= 1
    assert all("proj-page-01" in (it["id"] or "") for it in hits)


def test_org_and_project_members_pagination(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/orgs",
        headers=h,
        json={"id": "org-page", "name": "分页组织"},
    )
    assert r.status_code == 200, r.text

    for i in range(55):
        uname = f"orgmem{i:02d}"
        r = client.post(
            "/api/v1/auth/users",
            headers=h,
            json={"username": uname, "password": "Test1234!", "duty": "user"},
        )
        assert r.status_code == 200, r.text
        r = client.post(
            "/api/v1/orgs/org-page/members",
            headers=h,
            json={"username": uname, "role": "member"},
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/orgs/org-page/members?limit=50&offset=0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert page_total(body) >= 55
    assert len(page_items(body)) == 50

    r = client.get("/api/v1/orgs/org-page/members?limit=50&offset=50", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) >= 5

    r = client.get("/api/v1/orgs?page=1&page_size=50", headers=h)
    assert r.status_code == 200
    orgs_body = r.json()
    assert "items" in orgs_body
    assert page_total(orgs_body) >= 1
    assert any(o["id"] == "org-page" for o in page_items(orgs_body))

    r = client.post(
        "/api/v1/projects",
        headers=h,
        json={"id": "proj-mem-page", "name": "成员分页", "org_id": "org-page"},
    )
    assert r.status_code == 200, r.text

    for i in range(55):
        uname = f"projmem{i:02d}"
        r = client.post(
            "/api/v1/auth/users",
            headers=h,
            json={"username": uname, "password": "Test1234!", "duty": "user"},
        )
        assert r.status_code == 200, r.text
        r = client.post(
            "/api/v1/projects/proj-mem-page/members",
            headers=h,
            json={"username": uname, "role": "member"},
        )
        assert r.status_code == 200, r.text

    r = client.get(
        "/api/v1/projects/proj-mem-page/members?limit=50&offset=0", headers=h
    )
    assert r.status_code == 200
    body = r.json()
    assert page_total(body) >= 55
    assert len(page_items(body)) == 50

    r = client.get(
        "/api/v1/projects/proj-mem-page/members?limit=50&offset=50", headers=h
    )
    assert r.status_code == 200
    assert len(page_items(r.json())) >= 5


def test_devices_list_and_board_pagination(client: TestClient):
    h = _login(client)
    rid = "dev-pager"
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "hostname": "host-pager",
            "version": "0.1.0",
            "capabilities": ["android"],
        },
    )
    assert r.status_code == 200, r.text

    devices = [
        {"udid": f"dev-{i:03d}", "platform": "android", "name": f"D{i}"}
        for i in range(55)
    ]
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "status": "idle", "inventory": devices, "devices": devices},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/v1/devices?limit=50&offset=0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert page_total(body) >= 55
    assert len(page_items(body)) == 50

    r = client.get("/api/v1/devices?limit=50&offset=50", headers=h)
    assert r.status_code == 200
    assert len(page_items(r.json())) >= 5

    r = client.get("/api/v1/devices?page=1&page_size=10", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert len(page_items(body)) == 10

    r = client.get("/api/v1/devices/board?limit=10&offset=0", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["online"] >= 55
    assert len(body["devices"]) == 10

    r = client.get("/api/v1/devices/board?summary_only=true", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["online"] >= 55
    assert body["devices"] == []

    r = client.get("/api/v1/devices?limit=50&platform=android", headers=h)
    assert r.status_code == 200
    assert all(d.get("platform") == "android" for d in page_items(r.json()))

    r = client.get("/api/v1/devices?limit=50&q=dev-001", headers=h)
    assert r.status_code == 200
    items = page_items(r.json())
    assert len(items) == 1
    assert items[0]["udid"] == "dev-001"
