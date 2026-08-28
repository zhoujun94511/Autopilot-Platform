"""无项目通用闲聊：不落设计域、不注入知识库。"""

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

from list_page_helpers import page_items, page_total

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


def test_ephemeral_chat_no_design_session_and_no_rag(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)

    def boom_rag(*_a, **_k):
        raise AssertionError("ephemeral chat must not touch RAG")

    monkeypatch.setattr(
        "autopilot_platform.platform.rag.service.retrieve_for_generation",
        boom_rag,
    )

    captured = {}

    def fake_chat(_messages, **_kwargs):
        captured["messages"] = _messages
        return "通用闲聊回复"

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )

    r = client.post(
        "/api/v1/ops/ai/chat",
        headers=h,
        json={
            "message": "你好，随便聊聊",
            "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("success") is True
    assert out.get("ephemeral") is True
    assert out.get("response") == "通用闲聊回复"

    msgs = captured.get("messages") or []
    assert msgs
    assert msgs[0]["role"] == "system"
    assert "测试小助手" in msgs[0]["content"]
    assert msgs[0]["content"].startswith("你是 Autopilot 测试小助手")
    assert "参考知识库：" not in msgs[0]["content"]
    assert "无项目闲聊" in msgs[0]["content"]

    # 设计域会话表不应因闲聊产生记录
    r = client.get("/api/v1/design/chat/sessions", headers=h)
    assert r.status_code == 200
    assert page_items(r.json()) == []
    assert page_total(r.json()) == 0


def test_ephemeral_chat_stream_token(client: TestClient, monkeypatch):
    h = _login(client)
    _enable_ai(monkeypatch)

    def fake_stream(_messages, **_kwargs):
        yield "闲"
        yield "聊"

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions_stream",
        fake_stream,
    )

    events = []
    with client.stream(
        "POST",
        "/api/v1/ops/ai/chat/stream",
        headers=h,
        json={"message": "打个招呼"},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                for line in part.split("\n"):
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:].strip()))

    types = [e.get("type") for e in events]
    assert "start" in types
    assert "chunk" in types
    assert "end" in types
    assert all(e.get("ephemeral") for e in events if e.get("type") in {"start", "chunk", "end"})
    end = next(e for e in events if e.get("type") == "end")
    assert end.get("full_response") == "闲聊"

    r = client.get("/api/v1/design/chat/sessions", headers=h)
    assert r.status_code == 200
    assert page_items(r.json()) == []
    assert page_total(r.json()) == 0


def test_build_messages_general_prompt_without_project(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    from autopilot_platform.platform.design.design_models import DesignChatSessionRow
    from autopilot_platform.platform.services.design.chat import messages as chat_messages
    from autopilot_platform.platform.services.design.chat import prompts as chat_svc

    session = DesignChatSessionRow(
        id="s1",
        project_id="",
        title="t",
        created_by="u",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db = MagicMock()

    def boom(*_a, **_k):
        raise AssertionError("no project => no RAG")

    monkeypatch.setattr(
        "autopilot_platform.platform.rag.service.retrieve_for_generation",
        boom,
    )
    monkeypatch.setattr(chat_messages, "list_messages", lambda *_a, **_k: [])
    msgs = chat_svc._build_messages(db, session, "你好", use_knowledge=True)
    assert msgs[0]["role"] == "system"
    assert "测试小助手" in msgs[0]["content"]
    assert "无项目闲聊" in msgs[0]["content"]
    assert "参考知识库：" not in msgs[0]["content"]


def test_starter_suggestions_match_welcome_questions():
    from autopilot_platform.platform.services.design.chat.suggestions import (
        starter_suggestions,
    )

    qs = starter_suggestions()
    assert "如何开展测试用例设计和评审工作？" in qs
    assert "如何开展性能测试？" in qs
    assert len(qs) >= 5
