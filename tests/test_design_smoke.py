"""设计域 API 冒烟：需求 / 逻辑用例 / 知识 / stats。"""

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


def test_design_domain_smoke(client: TestClient):
    h = _login(client)

    r = client.post(
        "/api/v1/design/requirements",
        headers=h,
        json={
            "project_id": "p-smoke",
            "title": "登录可用",
            "content": "用户可登录",
            "priority": "P1",
        },
    )
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]

    r = client.get(f"/api/v1/design/requirements/{req_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "登录可用"

    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-smoke",
            "title": "登录主路径",
            "logical_steps": ["打开登录页", "输入账号密码", "点击登录"],
            "expected_results": ["进入首页"],
            "source_requirement_ids": [req_id],
            "review_status": "APPROVED",
        },
    )
    assert r.status_code == 200, r.text
    case = r.json()
    case_id = case["logical_case_id"]
    assert case.get("schema_version") == "2.0"
    assert case.get("automation_status") == "INTENT_READY"
    assert isinstance(case.get("intent_steps"), list) and case["intent_steps"]
    assert any(s.get("action") for s in case["intent_steps"])

    r = client.get(
        "/api/v1/design/projects/p-smoke/logical-cases/export",
        headers=h,
    )
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle.get("schema_version") == "2.0"
    assert bundle["cases"]
    assert bundle["cases"][0].get("intent_steps")

    r = client.patch(
        f"/api/v1/design/logical-cases/{case_id}",
        headers=h,
        json={"automation_status": "DEBUGGING"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["automation_status"] == "DEBUGGING"

    r = client.post(
        "/api/v1/design/knowledge",
        headers=h,
        json={
            "project_id": "p-smoke",
            "title": "登录约定",
            "content": "账号密码错误三次锁定",
            "category": "rule",
        },
    )
    assert r.status_code == 200, r.text
    kid = r.json()["id"]

    r = client.get(f"/api/v1/design/knowledge/{kid}", headers=h)
    assert r.status_code == 200

    r = client.get("/api/v1/design/stats?project_id=p-smoke", headers=h)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["requirements"] >= 1
    assert stats["logical_cases"] >= 1
    assert stats["knowledge"] >= 1
    assert stats["by_automation_status"].get("DEBUGGING", 0) >= 1

    r = client.get("/api/v1/design/projects/p-smoke/logical-cases/export", headers=h)
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert any(c.get("logical_case_id") == case_id for c in bundle.get("cases") or [])


def test_generate_auto_approve_high_quality(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=h,
        json={
            "project_id": "p-auto",
            "requirement_text": (
                "用户打开登录页，输入用户名和密码，点击登录按钮，"
                "成功后进入首页并看到欢迎文案。"
            ),
            "max_cases": 1,
            "auto_approve": True,
            "auto_approve_min_quality": 0.5,
        },
    )
    assert r.status_code == 200, r.text
    cases = r.json()
    assert cases
    # 半自动：达标则 APPROVED+PENDING_VERIFY，否则仍 AI_DRAFT
    assert cases[0]["review_status"] in ("APPROVED", "AI_DRAFT")
    meta = cases[0].get("generation_metadata") or {}
    assert "quality" in meta
    assert meta["quality"].get("review_bucket") in (
        "auto_approvable",
        "needs_review",
        "reject_suggest",
    )
    if cases[0]["review_status"] == "APPROVED":
        assert meta.get("auto_approved") is True
        assert cases[0].get("automation_status") == "PENDING_VERIFY"
        assert meta.get("pending_first_run") is True
