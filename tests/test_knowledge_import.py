"""知识批量导入 API。"""

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


def test_knowledge_import_multi_files(client: TestClient):
    h = _login(client)
    md = "# 登录\n\n密码错误三次锁定\n\n## 注册\n\n邮箱需验证\n".encode("utf-8")
    js = json.dumps(
        [
            {"title": "iOS 弹框", "content": "首次安装允许通知", "category": "best_practices"},
            {"title": "Android 权限", "content": "存储权限按需申请"},
        ],
        ensure_ascii=False,
    ).encode("utf-8")
    csv_body = "title,content\n超时重试,网络失败自动重试三次\n".encode("utf-8")

    files = [
        ("files", ("login.md", io.BytesIO(md), "text/markdown")),
        ("files", ("tips.json", io.BytesIO(js), "application/json")),
        ("files", ("rules.csv", io.BytesIO(csv_body), "text/csv")),
    ]
    data = {
        "project_id": "p-import",
        "category": "best_practices",
        "confirmed": "true",
        "description": "batch-test",
    }
    r = client.post("/api/v1/design/knowledge/import", headers=h, data=data, files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["success_count"] == 3
    assert body["summary"]["failed_count"] == 0
    assert body["summary"]["item_count"] >= 4

    r = client.get("/api/v1/design/knowledge?project_id=p-import", headers=h)
    assert r.status_code == 200, r.text
    titles = {x["title"] for x in r.json()}
    assert "登录" in titles or any("登录" in t for t in titles)
    assert "iOS 弹框" in titles
    assert "超时重试" in titles
