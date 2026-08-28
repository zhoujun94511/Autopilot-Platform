"""链路 3：POST /ops/ai/codegen 持钥网关（能力门禁 / 计费作用域 / 审计）。"""

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
from autopilot_platform.platform.tenancy.capability_registry import (
    CAPABILITY_IDS,
    CAPABILITY_ROUTE_BINDINGS,
)


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
    monkeypatch.setenv("MC_API_TOKEN", "runner-token-test")
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _enable_ai(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()


def test_codegen_capability_registered():
    assert "cap.ops.ai.codegen" in CAPABILITY_IDS
    hits = [
        b
        for b in CAPABILITY_ROUTE_BINDINGS
        if b.capability_id == "cap.ops.ai.codegen"
        and b.path == "/api/v1/ops/ai/codegen"
        and b.method == "POST"
    ]
    assert hits, "POST /ops/ai/codegen 须绑定 cap.ops.ai.codegen"
    assert hits[0].guard == "authenticated"


def test_codegen_requires_auth(client: TestClient):
    r = client.post("/api/v1/ops/ai/codegen", json={"prompt": "{}"})
    assert r.status_code in (401, 403)


def test_codegen_rejects_runner_token(client: TestClient, monkeypatch):
    _enable_ai(monkeypatch)
    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers={"X-API-Token": "runner-token-test"},
        json={"prompt": '{"steps":[]}'},
    )
    assert r.status_code == 403, r.text


def test_codegen_forwards_with_billing_scope(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)

    captured: dict = {}

    def fake_chat(messages, **_kwargs):
        from autopilot_platform.platform.ai import ai_usage

        captured["scope"] = ai_usage.get_ai_billing_scope()
        captured["messages"] = messages
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
    assert out.get("ok") is True
    assert "steps" in (out.get("content") or "")
    scope = captured.get("scope") or {}
    assert scope.get("project_id"), "计费 project_id 不得为空"
    assert scope.get("org_id"), "计费 org_id 不得为空"
    assert out.get("project_id") == scope.get("project_id")
    assert out.get("org_id") == scope.get("org_id")

    # 审计应有记录
    from list_page_helpers import page_items

    audit = client.get("/api/v1/audit", headers=h, params={"action": "ops.ai_codegen"})
    assert audit.status_code == 200, audit.text
    actions = [it.get("action") for it in page_items(audit.json()) if isinstance(it, dict)]
    assert "ops.ai_codegen" in actions


def test_codegen_purpose_selects_locate_model(client: TestClient, monkeypatch):
    h = _login(client)
    monkeypatch.setenv("AP_AI_PLANNING_MODEL", "plan-m")
    monkeypatch.setenv("AP_AI_LOCATE_MODEL", "locate-m")
    _enable_ai(monkeypatch)

    captured: dict = {}

    def fake_chat(_messages, **_kwargs):
        captured["model"] = _kwargs.get("model")
        return '{"ok":true}'

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )

    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers=h,
        json={"prompt": "补 locator", "purpose": "locate", "project_id": ""},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("purpose") == "locate"
    assert out.get("model") == "locate-m"
    assert captured.get("model") == "locate-m"
    caps = out.get("capabilities") or {}
    assert caps.get("planning_model") == "plan-m"
    assert caps.get("locate_model") == "locate-m"


def test_ai_model_for_purpose_fallback(monkeypatch):
    from autopilot_platform.platform.ai import ai_config

    for k in (
        "AP_AI_MODEL",
        "AP_AI_PLANNING_MODEL",
        "AP_AI_LOCATE_MODEL",
        "MC_AI_MODEL",
        "OPENAI_MODEL",
        "DEEPSEEK_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_MODEL", "base-m")
    assert ai_config.ai_model_for_purpose("authoring") == "base-m"
    monkeypatch.setenv("AP_AI_PLANNING_MODEL", "plan-m")
    assert ai_config.ai_model_for_purpose("planning") == "plan-m"
    assert ai_config.ai_model_for_purpose("locate") == "plan-m"
    monkeypatch.setenv("AP_AI_LOCATE_MODEL", "loc-m")
    assert ai_config.ai_model_for_purpose("locate") == "loc-m"
