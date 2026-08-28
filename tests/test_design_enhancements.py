"""设计域增强 API 测试：删除/驳回/导出/知识检索/文档预览/配置/Chat。"""

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
    reset_engine()
    reload_runtime_config()


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_logical_case_reject_delete_export(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-enh",
            "title": "待驳回用例",
            "logical_steps": ["步骤1"],
            "expected_results": ["结果1"],
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]

    r = client.patch(
        f"/api/v1/design/logical-cases/{case_id}",
        headers=h,
        json={"review_status": "REJECTED"},
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "REJECTED"

    r = client.get(
        "/api/v1/design/logical-cases",
        headers=h,
        params={"project_id": "p-enh", "review_status": "REJECTED"},
    )
    assert r.status_code == 200
    assert any(c["logical_case_id"] == case_id for c in r.json())

    r = client.post(
        "/api/v1/design/logical-cases/export",
        headers=h,
        json={"project_id": "p-enh", "format": "csv"},
    )
    assert r.status_code == 200
    assert "text/csv" in (r.headers.get("content-type") or "")
    assert b"logical_case_id" in r.content or "logical_case_id" in r.text
    assert b"intent_steps" in r.content or "intent_steps" in r.text

    r = client.get("/api/v1/design/logical-cases/template", headers=h, params={"format": "csv"})
    assert r.status_code == 200

    r = client.delete(f"/api/v1/design/logical-cases/{case_id}", headers=h)
    assert r.status_code == 204


def test_batch_generate_and_knowledge_search(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/knowledge",
        headers=h,
        json={
            "project_id": "p-enh",
            "title": "登录规则",
            "content": "用户名密码登录失败三次锁定",
            "category": "business_rules",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    kid = r.json()["id"]

    r = client.post(
        "/api/v1/design/knowledge/search",
        headers=h,
        json={"project_id": "p-enh", "query": "登录失败", "top_k": 5, "score_threshold": 0.0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["query"] == "登录失败"

    r = client.post(
        "/api/v1/design/knowledge/rebuild",
        headers=h,
        json={"project_id": "p-enh", "clear_all": True},
    )
    assert r.status_code == 200
    assert r.json().get("success") is True

    r = client.post(
        "/api/v1/design/logical-cases/batch-generate",
        headers=h,
        json={
            "project_id": "p-enh",
            "requirements": ["用户可登录", "用户可退出"],
            "case_count_per_req": 1,
            "process_mode": "sequential",
            "use_rag": False,
        },
    )
    assert r.status_code == 200, r.text
    assert int(r.json().get("total_cases") or 0) >= 1

    r = client.post(
        "/api/v1/design/knowledge/batch-delete",
        headers=h,
        json={"item_ids": [kid]},
    )
    assert r.status_code == 200
    assert int(r.json().get("deleted_count") or 0) == 1


def test_document_preview_history_and_config_chat(client: TestClient):
    h = _login(client)
    content = "## 登录\n\n用户可以登录系统。\n\n## 退出\n\n用户可以退出。".encode("utf-8")
    files = {"files": ("req.txt", content, "text/plain")}
    r = client.post(
        "/api/v1/design/documents/import",
        headers=h,
        data={
            "project_id": "p-enh",
            "auto_analyze": "true",
            "use_llm": "false",
            "max_requirements": "5",
        },
        files=files,
    )
    assert r.status_code == 200, r.text
    docs = r.json().get("documents") or []
    assert docs
    doc_id = docs[0]["id"] if isinstance(docs[0], dict) else docs[0]

    r = client.get(f"/api/v1/design/documents/{doc_id}/preview", headers=h)
    assert r.status_code == 200
    assert "登录" in (r.json().get("content") or "")

    r = client.post(
        f"/api/v1/design/documents/{doc_id}/reanalyze",
        headers=h,
        params={"use_llm": "false", "max_requirements": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert body.get("analysis_type") == "requirements"
    assert len(body.get("requirements") or []) >= 1

    r = client.get(
        "/api/v1/design/documents/analysis-history",
        headers=h,
        params={"project_id": "p-enh"},
    )
    assert r.status_code == 200
    assert page_total(r.json()) >= 1

    r = client.get(
        "/api/v1/design/requirements/export",
        headers=h,
        params={"project_id": "p-enh", "format": "csv"},
    )
    assert r.status_code == 200

    r = client.get("/api/v1/design/config", headers=h)
    assert r.status_code == 200
    assert "AP_AI_PROVIDER" in (r.json().get("values") or {})

    r = client.put(
        "/api/v1/design/config",
        headers=h,
        json={"values": {"AP_RAG_TOP_K": "7", "AP_RAG_SCORE_THRESHOLD": "0.25"}},
    )
    assert r.status_code == 200
    assert str(r.json()["values"].get("AP_RAG_TOP_K")) == "7"

    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=h,
        json={"project_id": "p-enh", "title": "测试会话"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.get("/api/v1/design/chat/sessions", headers=h, params={"project_id": "p-enh"})
    assert r.status_code == 200
    assert any(s["id"] == sid for s in page_items(r.json()))

    # 无 AI Key 时 message 应 503；仍可导出空会话
    r = client.get(f"/api/v1/design/chat/sessions/{sid}/export", headers=h)
    assert r.status_code == 200
    assert r.json().get("session", {}).get("id") == sid

    r = client.delete(f"/api/v1/design/chat/sessions/{sid}", headers=h)
    assert r.status_code == 204


def test_chat_stream_token_mode(client: TestClient, monkeypatch):
    """上游 stream 可用时，SSE 应边生成边推（stream_mode=token）。"""
    h = _login(client)
    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=h,
        json={"project_id": "p-enh", "title": "stream"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    def fake_stream(_messages, **_kwargs):
        yield "你好"
        yield "，"
        yield "世界"

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions_stream",
        fake_stream,
    )

    events = []
    with client.stream(
        "POST",
        "/api/v1/design/chat/stream",
        headers=h,
        json={"session_id": sid, "message": "打个招呼", "use_knowledge": False},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                for line in part.split("\n"):
                    if line.startswith("data:"):
                        import json

                        events.append(json.loads(line[5:].strip()))

    types = [e.get("type") for e in events]
    assert "start" in types
    assert "chunk" in types
    assert "end" in types
    assert any(e.get("stream_mode") == "token" for e in events if e.get("type") == "start")
    assert any(e.get("stream_mode") == "token" for e in events if e.get("type") == "end")
    end = next(e for e in events if e.get("type") == "end")
    assert end.get("full_response") == "你好，世界"

    r = client.get(f"/api/v1/design/chat/sessions/{sid}/messages", headers=h)
    assert r.status_code == 200
    msgs = r.json()
    assert any(m["role"] == "assistant" and m["content"] == "你好，世界" for m in msgs)


def test_chat_stream_buffered_fallback(client: TestClient, monkeypatch):
    """上游 stream 失败时，应降级为 buffered 并仍返回完整回复。"""
    h = _login(client)
    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=h,
        json={"project_id": "p-enh", "title": "fallback"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    def boom(_messages, **_kwargs):
        raise RuntimeError("upstream stream not supported")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions_stream",
        boom,
    )
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        lambda messages, **kwargs: "降级回复ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )

    events = []
    with client.stream(
        "POST",
        "/api/v1/design/chat/stream",
        headers=h,
        json={"session_id": sid, "message": "hello", "use_knowledge": False},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                for line in part.split("\n"):
                    if line.startswith("data:"):
                        import json

                        events.append(json.loads(line[5:].strip()))

    assert any(e.get("stream_mode") == "buffered" for e in events)
    end = next(e for e in events if e.get("type") == "end")
    assert "降级回复" in (end.get("full_response") or "")


def test_chat_session_product_apis(client: TestClient, monkeypatch):
    """重命名 / 清空 / 多格式导出 / options / 模型参数透传。"""
    h = _login(client)
    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=h,
        json={"project_id": "p-enh", "title": "旧标题"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.patch(
        f"/api/v1/design/chat/sessions/{sid}",
        headers=h,
        json={"title": "新标题"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "新标题"

    r = client.get("/api/v1/design/chat/options", headers=h)
    assert r.status_code == 200
    opts = r.json()
    assert "available_models" in opts
    assert "default_model" in opts
    assert "key_configured" in opts
    assert isinstance(opts.get("templates"), list)

    r = client.get("/api/v1/design/chat/templates", headers=h)
    assert r.status_code == 200
    assert "test_strategy" in (r.json().get("templates") or {})

    r = client.get("/api/v1/design/chat/suggestions", headers=h)
    assert r.status_code == 200
    assert len(r.json().get("suggestions") or []) >= 1

    # 写入一条消息以便导出有内容
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    captured: dict = {}

    def fake_chat(_messages, **_kwargs):
        captured.update(_kwargs)
        return "助手回复内容，含用例建议"

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions",
        fake_chat,
    )
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_client.chat_completions_stream",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no stream")),
    )

    r = client.post(
        "/api/v1/design/chat/message",
        headers=h,
        json={
            "session_id": sid,
            "message": "请帮我写用例",
            "use_knowledge": False,
            "model": "gpt-4o-mini",
            "temperature": 0.2,
        },
    )
    assert r.status_code == 200, r.text
    assert captured.get("model") == "gpt-4o-mini"
    assert captured.get("temperature") == 0.2
    assert r.json().get("suggestions")

    r = client.get("/api/v1/design/chat/sessions", headers=h, params={"project_id": "p-enh"})
    assert r.status_code == 200
    row = next(s for s in page_items(r.json()) if s["id"] == sid)
    assert row["message_count"] >= 2
    assert row.get("preview")

    for fmt, ctype in (
        ("json", "application/json"),
        ("txt", "text/plain"),
        ("csv", "text/csv"),
        ("xlsx", "spreadsheetml"),
    ):
        r = client.get(
            f"/api/v1/design/chat/sessions/{sid}/export",
            headers=h,
            params={"format": fmt},
        )
        assert r.status_code == 200, r.text
        assert ctype in (r.headers.get("content-type") or "")

    r = client.post(f"/api/v1/design/chat/sessions/{sid}/clear", headers=h)
    assert r.status_code == 200
    assert r.json().get("cleared_messages", 0) >= 1
    r = client.get(f"/api/v1/design/chat/sessions/{sid}/messages", headers=h)
    assert r.status_code == 200
    assert r.json() == []


def test_chat_build_messages_language_and_pairing():
    from autopilot_platform.platform.services.design.chat import prompts as chat_svc
    from autopilot_platform.platform.design.design_schemas import ChatMessageOut
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    hist = [
        ChatMessageOut(
            id="1",
            session_id="s",
            role="user",
            content="hello",
            created_at=now,
        ),
        ChatMessageOut(
            id="2",
            session_id="s",
            role="assistant",
            content="hi",
            created_at=now,
        ),
        ChatMessageOut(
            id="3",
            session_id="s",
            role="user",
            content="hello",  # 重复应跳过
            created_at=now,
        ),
    ]
    paired = chat_svc._pair_history(hist, current_user="新问题")
    assert paired == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    zh = chat_svc._infer_language_instruction("请帮我写测试用例")
    assert "简体中文" in zh
    en = chat_svc._infer_language_instruction("Please write test cases")
    assert "English" in en


def test_batch_generate_parallel_note(client: TestClient, monkeypatch):
    """process_mode=parallel 且开启并行开关时真正并行，summary 标明 executed_mode。"""
    h = _login(client)
    monkeypatch.setattr(
        "autopilot_platform.platform.ops.runtime_config.parallel_processing_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "autopilot_platform.platform.ops.runtime_config.design_max_workers",
        lambda: 2,
    )

    def fake_gen(_db, req, _auth):
        from datetime import datetime, timezone

        from autopilot_platform.platform.design.design_schemas import LogicalCaseOut

        now = datetime.now(timezone.utc)
        return [
            LogicalCaseOut(
                logical_case_id="lc-1",
                case_key="C-1",
                project_id=req.project_id,
                revision_id="r1",
                title="t",
                review_status="AI_DRAFT",
                automatability="UNKNOWN",
                automation_status="LOGICAL_ONLY",
                created_at=now,
                updated_at=now,
            )
        ]

    monkeypatch.setattr(
        "autopilot_platform.platform.services.design.cases.generation.generate_logical_cases",
        fake_gen,
    )
    r = client.post(
        "/api/v1/design/logical-cases/batch-generate",
        headers=h,
        json={
            "project_id": "p-enh",
            "requirements": ["需求A", "需求B"],
            "case_count_per_req": 1,
            "process_mode": "parallel",
            "use_rag": False,
        },
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["summary"]["process_mode"] == "parallel"
    assert payload["summary"]["executed_mode"] == "sequential"
    assert "SQLite" in (payload["summary"].get("note") or "")


def test_batch_generate_parallel_disabled_falls_back(client: TestClient, monkeypatch):
    h = _login(client)
    monkeypatch.setattr(
        "autopilot_platform.platform.ops.runtime_config.parallel_processing_enabled",
        lambda: False,
    )

    def fake_gen(_db, req, _auth):
        from datetime import datetime, timezone

        from autopilot_platform.platform.design.design_schemas import LogicalCaseOut

        now = datetime.now(timezone.utc)
        return [
            LogicalCaseOut(
                logical_case_id="lc-2",
                case_key="C-2",
                project_id=req.project_id,
                revision_id="r1",
                title="t",
                review_status="AI_DRAFT",
                automatability="UNKNOWN",
                automation_status="LOGICAL_ONLY",
                created_at=now,
                updated_at=now,
            )
        ]

    monkeypatch.setattr(
        "autopilot_platform.platform.services.design.cases.generation.generate_logical_cases",
        fake_gen,
    )
    r = client.post(
        "/api/v1/design/logical-cases/batch-generate",
        headers=h,
        json={
            "project_id": "p-enh",
            "requirements": ["需求A", "需求B"],
            "case_count_per_req": 1,
            "process_mode": "parallel",
            "use_rag": False,
        },
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["summary"]["executed_mode"] == "sequential"
    assert "AP_ENABLE_PARALLEL_PROCESSING=0" in (payload["summary"].get("note") or "")


def test_chat_session_owner_isolation(client: TestClient):
    """他人不得凭 session_id 读写会话（created_by 归属）。"""
    admin = _login(client)
    r = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": "chatbob", "password": "Bob12345!", "duty": "user"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/login", json={"username": "chatbob", "password": "Bob12345!"}
    )
    assert r.status_code == 200, r.text
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post(
        "/api/v1/design/chat/sessions",
        headers=admin,
        json={"project_id": "p-enh", "title": "admin-only"},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.get(f"/api/v1/design/chat/sessions/{sid}/messages", headers=other)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/design/chat/sessions/{sid}/export", headers=other)
    assert r.status_code == 403, r.text
    r = client.delete(f"/api/v1/design/chat/sessions/{sid}", headers=other)
    assert r.status_code == 403, r.text

    r = client.get(f"/api/v1/design/chat/sessions/{sid}/messages", headers=admin)
    assert r.status_code == 200, r.text


def test_comprehensive_part_failure_marks_degraded(client: TestClient, monkeypatch):
    """comprehensive 子分析抛错时 success 仍可达，但 degraded=true 且含 part_failures。"""
    h = _login(client)
    content = "登录功能\n\n用户可使用账号密码登录。"
    r = client.post(
        "/api/v1/design/documents",
        headers=h,
        params={"project_id": "p-enh"},
        files={"file": ("spec.txt", content.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    def boom(*_a, **_k):
        raise RuntimeError("inject-fail")

    monkeypatch.setattr(
        "autopilot_platform.platform.services.design.documents.analysis.pipeline._persist_test_points",
        boom,
    )
    r = client.post(
        f"/api/v1/design/documents/{doc_id}/analyze",
        headers=h,
        params={"analysis_type": "comprehensive", "use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("success") is True
    assert out.get("degraded") is True
    assert any("test_points" in str(x) for x in (out.get("part_failures") or []))
    assert "failed" in str(out.get("mode") or "")


def test_generate_rejects_degraded_when_flag_on(client: TestClient, monkeypatch):
    """AP_AI_REJECT_DEGRADED=1 时 LLM 失败返回 503，不落启发式草稿。"""
    h = _login(client)
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_config.ai_reject_degraded",
        lambda: True,
    )

    def boom(*_a, **_k):
        raise RuntimeError("llm-down")

    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_case_generator.generate_logical_case_drafts",
        boom,
    )
    r = client.post(
        "/api/v1/design/logical-cases/generate",
        headers=h,
        json={
            "project_id": "p-enh",
            "requirement_text": "用户登录后可查看订单列表",
            "max_cases": 2,
        },
    )
    assert r.status_code == 503, r.text
    blob = (r.text or "").lower()
    assert "reject_degraded" in blob or "假通" in r.text or "ai" in blob


def test_binding_evidence_attach_passed_and_failed(tmp_path):
    from autopilot_platform.runner.binding_evidence import attach_status_evidence

    tc = tmp_path / "login.tc.yaml"
    tc.write_text(
        "shells:\n"
        "  case:\n"
        "    - step: intent_act\n"
        "      remark: 'intent:click Login'\n"
        "    - step: click\n"
        "      remark: mapping_required\n",
        encoding="utf-8",
    )
    item: dict = {"logical_case_id": "lc-x", "name": "login"}
    attach_status_evidence(
        item, source_path=str(tc), project_dir=str(tmp_path), passed=False
    )
    assert item["mapping_required"] is True
    assert item["automation_status_evidence"] == "MAPPING_REQUIRED"

    item2: dict = {"logical_case_id": "lc-y"}
    tc2 = tmp_path / "ok.tc.yaml"
    tc2.write_text(
        "shells:\n  case:\n    - step: click\n      remark: plain\n",
        encoding="utf-8",
    )
    attach_status_evidence(
        item2, source_path=str(tc2), project_dir=str(tmp_path), passed=True
    )
    assert item2["mapping_required"] is False
    assert item2["automation_status_evidence"] == "EXECUTABLE"
