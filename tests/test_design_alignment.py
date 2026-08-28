"""设计域对齐增强：配置导入导出、分析分流、用例运维、统计导出、实验动作。"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from io import BytesIO

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


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
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_design_config_categories_import_export_validate(client: TestClient):
    h = _login(client)
    r = client.get("/api/v1/design/config", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    cat_ids = {c["id"] for c in body.get("categories") or []}
    assert "case_generation" in cat_ids
    assert "performance" in cat_ids
    assert "file_processing" in cat_ids
    assert "AP_MAX_CASE_NUM" in (body.get("values") or {})

    r = client.put(
        "/api/v1/design/config",
        headers=h,
        json={"values": {"AP_MAX_CASE_NUM": "9999"}},
    )
    assert r.status_code == 400

    r = client.put(
        "/api/v1/design/config",
        headers=h,
        json={
            "values": {
                "AP_MAX_CASE_NUM": "12",
                "AP_CHUNK_SIZE": "2000",
                "AP_MAX_MEMORY_MB": "256",
                "AP_ENABLE_EXPERIMENTAL_ACTIONS": "true",
            }
        },
    )
    assert r.status_code == 200, r.text
    assert str(r.json()["values"].get("AP_MAX_CASE_NUM")) == "12"

    r = client.get("/api/v1/design/config/export", headers=h)
    assert r.status_code == 200
    exported = r.json()
    assert exported.get("format") == "autopilot-design-config"
    assert str(exported["values"].get("AP_CHUNK_SIZE")) == "2000"

    r = client.post(
        "/api/v1/design/config/import",
        headers=h,
        json={"values": {"AP_MAX_WORKERS": "4", "AP_ENABLE_STREAMING": "true"}},
    )
    assert r.status_code == 200, r.text
    assert str(r.json()["values"].get("AP_MAX_WORKERS")) == "4"


def test_document_analysis_type_branching(client: TestClient):
    h = _login(client)
    content = "登录功能\n\n用户可使用账号密码登录系统。\n\n边界：密码为空应提示错误。"
    r = client.post(
        "/api/v1/design/documents",
        headers=h,
        params={"project_id": "p-ana"},
        files={"file": ("spec.txt", content.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "test_points", "use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["analysis_type"] == "test_points"
    assert len(out.get("test_points") or []) >= 1
    assert (out.get("requirements") or []) == []

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "business_rules", "use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["analysis_type"] == "business_rules"
    assert len(out.get("business_rules") or []) >= 1
    assert "condition" in (out["business_rules"][0] or {})
    # 业务规则应落知识库
    r = client.get(
        "/api/v1/design/knowledge",
        headers=h,
        params={"project_id": "p-ana", "category": "business_rules"},
    )
    assert r.status_code == 200
    items = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
    assert len(items) >= 1

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "comprehensive", "use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["analysis_type"] == "comprehensive"
    assert out["summary"]["total_count"] >= 1

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "unknown_type", "use_llm": "false"},
    )
    assert r.status_code == 400


def test_logical_case_regenerate_batch_delete_json_export(client: TestClient):
    h = _login(client)
    ids = []
    for title in ("用例A", "用例B", "用例C"):
        r = client.post(
            "/api/v1/design/logical-cases",
            headers=h,
            json={
                "project_id": "p-ops",
                "title": title,
                "logical_steps": ["步骤1"],
                "expected_results": ["结果1"],
            },
        )
        assert r.status_code == 200, r.text
        ids.append(r.json()["logical_case_id"])

    r = client.post(
        f"/api/v1/design/logical-cases/{ids[0]}/regenerate",
        headers=h,
        json={"max_cases": 1, "use_rag": False},
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1

    r = client.post(
        "/api/v1/design/logical-cases/export",
        headers=h,
        json={"project_id": "p-ops", "format": "json", "case_ids": ids[:2]},
    )
    assert r.status_code == 200
    ctype = r.headers.get("content-type") or ""
    assert "json" in ctype
    payload = json.loads(r.content.decode("utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 2

    r = client.post(
        "/api/v1/design/logical-cases/batch-delete",
        headers=h,
        json={"case_ids": ids[1:]},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("deleted_count") == 2


def test_design_stats_csv_and_batch_zip(client: TestClient):
    h = _login(client)
    client.post(
        "/api/v1/design/requirements",
        headers=h,
        json={"project_id": "p-dash", "title": "需求1", "content": "内容"},
    )
    client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-dash",
            "title": "用例",
            "logical_steps": ["s"],
            "expected_results": ["e"],
        },
    )

    r = client.get("/api/v1/design/stats", headers=h, params={"project_id": "p-dash"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("requirements") >= 1
    assert "usage" in body or "tokens" in body

    r = client.get("/api/v1/design/stats/export", headers=h, params={"project_id": "p-dash"})
    assert r.status_code == 200
    assert b"requirements" in r.content or "requirements" in r.text

    r = client.post(
        "/api/v1/design/export/batch",
        headers=h,
        json={
            "project_id": "p-dash",
            "config": {
                "export_cases": True,
                "export_requirements": True,
                "export_knowledge": True,
            },
        },
    )
    assert r.status_code == 200
    assert "zip" in (r.headers.get("content-type") or "")
    zf = zipfile.ZipFile(BytesIO(r.content))
    names = set(zf.namelist())
    assert "manifest.json" in names
    assert "logical_cases.json" in names
    assert "requirements.json" in names


def test_experimental_action_generate_and_delete(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=h,
        json={"project_id": "p-exp", "title": "动作"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.post(
        "/api/v1/design/chat/message",
        headers=h,
        json={
            "session_id": sid,
            "message": "生成用例：用户登录成功后进入首页",
            "mode": "action",
            "require_confirmation": True,
            "use_knowledge": False,
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("status") == "needs_confirmation"
    eid = out["execution_id"]
    assert (out.get("plan") or out.get("action_plan") or {}).get("tool_name") == "generate_logical_cases"

    r = client.post(
        "/api/v1/design/experimental-actions/confirm",
        headers=h,
        json={"execution_id": eid, "metadata": {"project_id": "p-exp"}},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True
    assert (r.json().get("tool_output") or {}).get("count", 0) >= 1

    # 列出用例并走删除提议
    r = client.get("/api/v1/design/logical-cases", headers=h, params={"project_id": "p-exp"})
    assert r.status_code == 200
    cases = r.json()
    assert cases
    case_id = cases[0]["logical_case_id"]

    r = client.post(
        "/api/v1/design/chat/message",
        headers=h,
        json={
            "session_id": sid,
            "message": f"删除用例 {case_id}",
            "mode": "action",
            "use_knowledge": False,
        },
    )
    assert r.status_code == 200
    assert r.json().get("status") == "needs_confirmation"
    eid2 = r.json()["execution_id"]

    r = client.post(
        "/api/v1/design/experimental-actions/cancel",
        headers=h,
        json={"execution_id": eid2, "reason": "test"},
    )
    assert r.status_code == 200
    assert r.json().get("status") == "cancelled"


def test_experimental_action_confirm_requires_proposer(client: TestClient):
    admin = _login(client)
    r = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": "expbob", "password": "Bob12345!", "duty": "user"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/login", json={"username": "expbob", "password": "Bob12345!"}
    )
    assert r.status_code == 200, r.text
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=admin,
        json={"project_id": "p-exp", "title": "owner"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.post(
        "/api/v1/design/chat/message",
        headers=admin,
        json={
            "session_id": sid,
            "message": "生成用例：用户登录成功后进入首页",
            "mode": "action",
            "require_confirmation": True,
            "use_knowledge": False,
        },
    )
    assert r.status_code == 200, r.text
    eid = r.json()["execution_id"]

    r = client.post(
        "/api/v1/design/experimental-actions/confirm",
        headers=other,
        json={"execution_id": eid, "metadata": {"project_id": "p-exp"}},
    )
    assert r.status_code == 403, r.text
