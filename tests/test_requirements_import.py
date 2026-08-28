"""需求 / 文档批量导入 API（对齐 TestPilot 文档入口 + 结构化导入）。"""

from __future__ import annotations

import io
import json
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


def test_requirements_structured_import(client: TestClient):
    h = _login(client)
    md = "# 登录安全\n\n密码错误三次锁定账号\n\n## 注册校验\n\n邮箱需验证后可登录\n".encode(
        "utf-8"
    )
    js = json.dumps(
        [
            {
                "title": "会话超时",
                "content": "空闲 30 分钟自动登出",
                "priority": "P1",
                "req_key": "REQ-SESSION",
            },
            {"title": "密码复杂度", "content": "至少 8 位含数字与字母", "priority": "high"},
        ],
        ensure_ascii=False,
    ).encode("utf-8")
    csv_body = "title,content,priority\n忘记密码,短信验证码重置,P2\n".encode("utf-8")

    files = [
        ("files", ("login.md", io.BytesIO(md), "text/markdown")),
        ("files", ("extra.json", io.BytesIO(js), "application/json")),
        ("files", ("ops.csv", io.BytesIO(csv_body), "text/csv")),
    ]
    r = client.post(
        "/api/v1/design/requirements/import",
        headers=h,
        data={"project_id": "p-req"},
        files=files,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["success_count"] == 3
    assert body["summary"]["failed_count"] == 0
    assert body["summary"]["item_count"] >= 4

    r = client.get("/api/v1/design/requirements?project_id=p-req", headers=h)
    assert r.status_code == 200, r.text
    titles = {x["title"] for x in r.json()}
    assert "会话超时" in titles
    assert "忘记密码" in titles
    assert any("登录" in t or "注册" in t for t in titles)


def test_documents_import_auto_analyze_heuristic(client: TestClient, monkeypatch):
    """无 AI Key 时回退启发式；多文件上传 + 自动分析。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MC_AI_API_KEY", raising=False)
    h = _login(client)
    doc1 = "# 支付\n\n支持微信与支付宝\n\n## 退款\n\n7 日内原路退回\n".encode("utf-8")
    doc2 = "库存扣减\n\n下单成功后扣减可售库存\n".encode("utf-8")
    files = [
        ("files", ("pay.md", io.BytesIO(doc1), "text/markdown")),
        ("files", ("stock.txt", io.BytesIO(doc2), "text/plain")),
    ]
    data = {
        "project_id": "p-docs",
        "auto_analyze": "true",
        "use_llm": "true",
        "analysis_type": "requirements",
        "max_requirements": "20",
    }
    r = client.post("/api/v1/design/documents/import", headers=h, data=data, files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["success_count"] == 2
    assert body["summary"]["analyzed_count"] >= 2

    r = client.get("/api/v1/design/documents?project_id=p-docs", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/api/v1/design/requirements?project_id=p-docs", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_document_analyze_use_llm_false(client: TestClient):
    h = _login(client)
    content = "# A\n\n正文甲\n\n## B\n\n正文乙\n".encode("utf-8")
    r = client.post(
        "/api/v1/design/documents?project_id=p-an",
        headers=h,
        files={"file": ("a.md", io.BytesIO(content), "text/markdown")},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze?max_requirements=10&use_llm=false",
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)
    assert len(body.get("requirements") or []) >= 1
