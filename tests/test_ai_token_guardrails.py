"""AI token 消耗护栏：门禁 / 输入上限 / 计费作用域 / 预算体检。"""

from __future__ import annotations

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

from autopilot_platform.platform.ai import ai_usage
from autopilot_platform.platform.api.ops import MAX_AI_PROMPT_CHARS
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
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _enable_ai(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()


def test_token_budgets_read_runtime_config(tmp_path, monkeypatch):
    """运维页面保存的预算必须生效，不能只读启动进程 env。"""
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "AP_AI_DAILY_TOKEN_BUDGET": "300000",
                "AP_AI_PROJECT_DAILY_TOKEN_BUDGET": "100000",
                "AP_AI_ORG_DAILY_TOKEN_BUDGET": "200000",
                "AP_AI_ENFORCE_TOKEN_BUDGET": "1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(path))
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    assert ai_usage.daily_token_budget() == 300000
    assert ai_usage.project_daily_token_budget() == 100000
    assert ai_usage.org_daily_token_budget() == 200000
    assert ai_usage.enforce_token_budget() is True


@pytest.mark.parametrize("path", ["/api/v1/ops/ai/chat", "/api/v1/ops/ai/chat/stream"])
def test_ai_chat_rejects_runner_token(client: TestClient, monkeypatch, path: str):
    _enable_ai(monkeypatch)
    r = client.post(
        path,
        headers={"X-API-Token": "runner-token-test"},
        json={"message": "hi"},
    )
    assert r.status_code == 403, r.text


def test_codegen_rejects_oversized_prompt(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)

    def fake_chat(_messages, **_kwargs):  # pragma: no cover — 不应被调用
        raise AssertionError("超长 prompt 不应转发到厂商")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers=h,
        json={"prompt": "x" * (MAX_AI_PROMPT_CHARS + 1)},
    )
    assert r.status_code == 413, r.text


def test_codegen_rejects_embedded_image_before_vendor_call(
    client: TestClient, monkeypatch
):
    h = _login(client)
    _enable_ai(monkeypatch)
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("内嵌图片不得转发到厂商")
        ),
    )
    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers=h,
        json={"prompt": "页面截图：data:image/png;base64,AAAA"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    msg = str(body.get("message") or body.get("detail") or "").lower()
    assert "图片" in msg or "image" in msg or "unsupported_image" in str(body).lower()


def test_codegen_uses_config_max_tokens_and_usage_source(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)
    monkeypatch.setenv("AP_AI_MAX_TOKENS", "3072")
    monkeypatch.setenv("AP_AI_CODEGEN_MAX_TOKENS", "1600")
    monkeypatch.setenv("AP_AI_CODEGEN_MAX_ATTEMPTS", "2")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    captured: dict = {}

    def fake_chat(_messages, **_kwargs):
        captured.update(_kwargs)
        captured["scope"] = ai_usage.get_ai_billing_scope()
        return '{"steps": []}'

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    r = client.post("/api/v1/ops/ai/codegen", headers=h, json={"prompt": "写个用例"})
    assert r.status_code == 200, r.text
    assert captured.get("max_tokens") == 1600
    assert captured.get("max_attempts") == 2
    assert captured.get("usage_source") == "codegen"
    scope = captured.get("scope") or {}
    assert scope.get("project_id") and scope.get("org_id")
    caps = r.json().get("capabilities") or {}
    assert caps.get("codegen_max_tokens") == 1600
    assert caps.get("codegen_max_attempts") == 2


def test_deepseek_capabilities_are_text_only_and_token_free(
    client: TestClient, monkeypatch
):
    h = _login(client)
    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-v4-flash")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("能力预检不得调用厂商模型")
        ),
    )
    r = client.get("/api/v1/ops/ai/capabilities", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provider"] == "deepseek"
    assert data["accepts_images"] is False
    assert data["image_policy"] == "text_only_ui_tree"


def test_codegen_rejects_foreign_project_billing(client: TestClient, monkeypatch):
    """project_id 决定计费归属，非成员不得把消耗甩给别人的项目。"""
    h = _login(client)
    _enable_ai(monkeypatch)

    def fake_chat(_messages, **_kwargs):  # pragma: no cover — 不应被调用
        raise AssertionError("越权计费不应转发到厂商")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    r = client.post(
        "/api/v1/ops/ai/codegen",
        headers=h,
        json={"prompt": "写个用例", "project_id": "not-a-project"},
    )
    assert r.status_code in (403, 404), r.text


def test_codegen_budget_exhausted_returns_429(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)

    def boom(**_kwargs):
        raise RuntimeError("AI 日 token 预算已用尽")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_usage.check_budget_before_call",
        boom,
    )
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        lambda messages, **kwargs: (_ for _ in ()).throw(
            AssertionError("预算用尽不应转发到厂商")
        ),
    )
    r = client.post("/api/v1/ops/ai/codegen", headers=h, json={"prompt": "写个用例"})
    assert r.status_code == 429, r.text


def test_ephemeral_chat_has_billing_scope(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)
    captured: dict = {}

    def fake_chat(_messages, **_kwargs):
        captured["scope"] = ai_usage.get_ai_billing_scope()
        return "ok"

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    r = client.post("/api/v1/ops/ai/chat", headers=h, json={"message": "hi"})
    assert r.status_code == 200, r.text
    scope = captured.get("scope") or {}
    assert scope.get("project_id"), "闲聊也须落到合成计费桶"
    assert scope.get("org_id")


def test_chat_message_length_capped():
    from pydantic import ValidationError

    from autopilot_platform.platform.design.design_schemas import (
        MAX_CHAT_HISTORY_ITEMS,
        MAX_CHAT_MESSAGE_CHARS,
        EphemeralChatIn,
    )

    with pytest.raises(ValidationError):
        EphemeralChatIn(message="x" * (MAX_CHAT_MESSAGE_CHARS + 1))
    with pytest.raises(ValidationError):
        EphemeralChatIn(
            message="hi",
            history=[{"role": "user", "content": "x"}] * (MAX_CHAT_HISTORY_ITEMS + 1),
        )


def test_batch_requirements_count_capped():
    from pydantic import ValidationError

    from autopilot_platform.platform.design.design_schemas import (
        MAX_BATCH_REQUIREMENTS,
        LogicalCaseBatchGenerateIn,
    )

    with pytest.raises(ValidationError):
        LogicalCaseBatchGenerateIn(
            project_id="p1",
            requirements=["req"] * (MAX_BATCH_REQUIREMENTS + 1),
        )


def test_budget_config_warnings(monkeypatch):
    monkeypatch.delenv("AP_AI_DAILY_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AP_AI_PROJECT_DAILY_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AP_AI_ORG_DAILY_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AP_AI_ENFORCE_TOKEN_BUDGET", raising=False)
    warns = ai_usage.budget_config_warnings()
    assert warns and "未配置任何 AI 日 token 预算" in warns[0]

    monkeypatch.setenv("AP_AI_DAILY_TOKEN_BUDGET", "100000")
    warns = ai_usage.budget_config_warnings()
    assert warns and "未开启拦截" in warns[0]

    monkeypatch.setenv("AP_AI_ENFORCE_TOKEN_BUDGET", "1")
    assert ai_usage.budget_config_warnings() == []


def test_embedder_respects_budget_and_wraps_http_error(monkeypatch):
    from autopilot_platform.platform.rag.openai_embedder import MAX_EMBED_ITEMS, OpenAIEmbedder

    emb = OpenAIEmbedder(base_url="https://example.test/v1", api_key="sk-test", model="m")

    with pytest.raises(RuntimeError, match="条数超上限"):
        emb.embed_texts(["x"] * (MAX_EMBED_ITEMS + 1))

    def blocked(**_kwargs):
        raise RuntimeError("AI 日 token 预算已用尽")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_usage.check_budget_before_call",
        blocked,
    )
    with pytest.raises(RuntimeError, match="预算已用尽"):
        emb.embed_texts(["hello"])
