"""幽灵配置接线：去重 / 分块 / 内存 / 流式开关。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_schemas import ChatMessageIn
from sqlalchemy.orm import Session


def test_content_dedup_filters_similar_drafts(monkeypatch):
    from autopilot_platform.platform.services.design.cases import dedup as mod

    monkeypatch.setattr(mod, "content_dedup_enabled", lambda: True)
    monkeypatch.setattr(mod, "content_similarity_threshold", lambda: 0.85)
    monkeypatch.setattr(mod, "content_dedup_batch_size", lambda: 50)

    class _FakeScalars:
        @staticmethod
        def all():
            return [
                SimpleNamespace(title="登录成功", logical_steps=["打开登录页", "输入账号", "点击登录"]),
            ]

    class _FakeDB:
        @staticmethod
        def scalars(_q):
            return _FakeScalars()

    drafts = [
        SimpleNamespace(title="登录成功", logical_steps=["打开登录页", "输入账号", "点击登录"]),
        SimpleNamespace(title="忘记密码", logical_steps=["点击忘记密码", "输入邮箱"]),
    ]
    kept, meta = mod.filter_duplicate_drafts(cast(Session, _FakeDB()), project_id="p1", drafts=drafts)
    assert meta["enabled"] is True
    assert meta["dropped"] == 1
    assert len(kept) == 1
    assert kept[0].title == "忘记密码"


def test_content_dedup_can_disable(monkeypatch):
    from autopilot_platform.platform.services.design.cases import dedup as mod

    monkeypatch.setattr(mod, "content_dedup_enabled", lambda: False)
    drafts = [
        SimpleNamespace(title="A", logical_steps=["1"]),
        SimpleNamespace(title="A", logical_steps=["1"]),
    ]
    kept, meta = mod.filter_duplicate_drafts(cast(Session, SimpleNamespace()), project_id="p1", drafts=drafts)
    assert meta["enabled"] is False
    assert len(kept) == 2


def test_split_text_chunks_respects_chunk_size():
    from autopilot_platform.platform.services.design.documents.analysis import (
        heuristics as docs,
    )

    text = "标题一\n" + ("字" * 100) + "\n\n标题二\n短内容"
    chunks = docs._split_text_chunks(text, max_items=10, chunk_limit=40)
    assert chunks
    assert all(len(c) <= 40 for c in chunks)


def test_save_document_rejects_over_memory(monkeypatch, tmp_path):
    from autopilot_platform.platform.services.design.documents import crud as docs

    monkeypatch.setattr(docs, "design_max_memory_mb", lambda: 1)
    monkeypatch.setattr(docs, "uploads_root", lambda: tmp_path)
    with pytest.raises(ValueError, match="AP_MAX_MEMORY_MB"):
        docs.save_document(
            db=cast(Session, SimpleNamespace()),
            project_id="p1",
            filename="big.txt",
            data=b"x" * (2 * 1024 * 1024),
            auth=cast(AuthContext, SimpleNamespace(username="u", user_id="1")),
        )


def test_streaming_disabled_uses_buffered(monkeypatch):
    from autopilot_platform.platform.services.design.chat import streaming as chat

    monkeypatch.setattr(chat, "streaming_enabled", lambda: False)
    monkeypatch.setattr(chat, "design_chunk_size", lambda: 1000)
    monkeypatch.setattr(
        chat,
        "get_session",
        lambda db, sid: SimpleNamespace(id=sid, project_id="p1"),
    )
    monkeypatch.setattr(chat, "_build_messages", lambda *a, **k: [{"role": "user", "content": "hi"}])
    monkeypatch.setattr(chat, "_resolve_model_name", lambda body: "m")
    monkeypatch.setattr(chat, "_resolve_call_kwargs", lambda body: {})
    monkeypatch.setattr(chat, "_persist_turn", lambda *a, **k: None)
    monkeypatch.setattr(chat, "simple_suggestions", lambda *a, **k: [])

    class _AI:
        @staticmethod
        def chat_completions(_messages, **_kwargs):
            return "hello-buffered"

        @staticmethod
        def chat_completions_stream(_messages, **_kwargs):
            raise AssertionError("stream should not be called when disabled")

    import autopilot_platform.platform.ai.ai_client as ai_client

    monkeypatch.setattr(ai_client, "chat_completions", _AI.chat_completions)
    monkeypatch.setattr(ai_client, "chat_completions_stream", _AI.chat_completions_stream)

    events = list(
        chat.iter_sse_chunks(
            db=cast(Session, SimpleNamespace()),
            body=cast(ChatMessageIn, SimpleNamespace(session_id="s1", message="hi", use_knowledge=False)),
            auth=cast(AuthContext, SimpleNamespace()),
        )
    )
    joined = "\n".join(events)
    assert "buffered" in joined
    assert "AP_ENABLE_STREAMING=0" in joined
    assert "hello-buffered" in joined
