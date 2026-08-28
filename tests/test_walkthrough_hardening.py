"""走查收紧：design/config 写权限、测试点 list、degraded、schedule entry_paths、导出 intent。"""

from __future__ import annotations

import csv
import io
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


def _admin(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _operator(client: TestClient, ah: dict) -> dict:
    r = client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "op-walk", "password": "Opuser12", "duty": "user"},
    )
    assert r.status_code == 200, r.text
    # 建项目并加入，便于设计域 GET
    assert client.post(
        "/api/v1/orgs", headers=ah, json={"id": "org-walk", "name": "Walk"}
    ).status_code == 200
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-walk"},
        json={"id": "p-walk", "name": "walk", "org_id": "org-walk"},
    )
    assert r.status_code in (200, 201, 409) or r.status_code == 200
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "op-walk", "password": "Opuser12"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_design_config_write_ops_admin_only(client: TestClient):
    ah = _admin(client)
    oh = _operator(client, ah)

    r = client.get("/api/v1/design/config", headers=oh)
    assert r.status_code == 200, r.text
    assert r.json().get("writable") is False
    assert "/ops/config" in str(r.json().get("write_via") or "")

    r = client.put(
        "/api/v1/design/config",
        headers=oh,
        json={"values": {"AP_RAG_TOP_K": "3"}},
    )
    assert r.status_code == 403

    r = client.post(
        "/api/v1/design/config/import",
        headers=oh,
        json={"values": {"AP_RAG_TOP_K": "3"}},
    )
    assert r.status_code == 403

    r = client.put(
        "/api/v1/design/config",
        headers=ah,
        json={"values": {"AP_RAG_TOP_K": "6"}},
    )
    assert r.status_code == 200, r.text
    assert str(r.json()["values"].get("AP_RAG_TOP_K")) == "6"


def test_test_points_list_and_business_rules_to_knowledge(client: TestClient):
    h = _admin(client)
    content = "登录功能\n\n用户可使用账号密码登录。\n\n边界：密码为空应提示错误。"
    r = client.post(
        "/api/v1/design/documents",
        headers=h,
        params={"project_id": "p-tp"},
        files={"file": ("spec.txt", content.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "comprehensive", "use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("degraded") is True or out.get("generator") == "heuristic"
    assert len(out.get("test_points") or []) >= 1
    assert len(out.get("business_rules") or []) >= 1

    r = client.get(
        "/api/v1/design/test-points",
        headers=h,
        params={"project_id": "p-tp"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("total", 0) >= 1
    assert len(body.get("items") or []) >= 1

    r = client.get(
        "/api/v1/design/knowledge",
        headers=h,
        params={"project_id": "p-tp", "category": "business_rules"},
    )
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
    assert len(items) >= 1


def test_generate_degraded_and_export_intent_steps(client: TestClient, monkeypatch):
    h = _admin(client)

    def _boom(*_a, **_k):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_case_generator.generate_logical_case_drafts",
        _boom,
    )

    r = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=h,
        json={
            "project_id": "p-deg",
            "requirement_text": "用户登录后进入首页",
            "max_cases": 1,
            "use_rag": False,
        },
    )
    assert r.status_code == 200, r.text
    cases = r.json()
    assert cases
    meta = cases[0].get("generation_metadata") or {}
    assert meta.get("degraded") is True
    assert str(meta.get("generator") or "").startswith("heuristic")

    r = client.post(
        "/api/v1/design/logical-cases/export",
        headers=h,
        json={"project_id": "p-deg", "format": "csv"},
    )
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert "intent_steps" in (reader.fieldnames or [])
    assert rows and rows[0].get("intent_steps")


def test_schedule_entry_paths_fire_into_job(client: TestClient, tmp_path):
    ah = _admin(client)
    # 最小制品 zip
    art_dir = tmp_path / "suite"
    art_dir.mkdir()
    (art_dir / "a.tc.yaml").write_text("name: a\nsteps: []\n", encoding="utf-8")
    (art_dir / "b.tc.yaml").write_text("name: b\nsteps: []\n", encoding="utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(art_dir / "a.tc.yaml", "a.tc.yaml")
        zf.write(art_dir / "b.tc.yaml", "b.tc.yaml")
    buf.seek(0)
    r = client.post(
        "/api/v1/artifacts",
        headers=ah,
        files={"file": ("suite.zip", buf.getvalue(), "application/zip")},
        data={"name": "suite", "project_id": "p-sched"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    r = client.post(
        "/api/v1/schedules",
        headers=ah,
        json={
            "name": "with-entries",
            "artifact_id": aid,
            "project_id": "p-sched",
            "platform": "android",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
            "entry_paths": ["a.tc.yaml"],
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json().get("entry_paths") == ["a.tc.yaml"]

    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=ah)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    assert jid
    r = client.get(f"/api/v1/jobs/{jid}", headers=ah)
    assert r.status_code == 200
    assert r.json().get("entry_paths") == ["a.tc.yaml"]
