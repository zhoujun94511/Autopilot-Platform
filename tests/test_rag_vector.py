"""向量 RAG 组件冒烟。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot_platform.platform.rag.hashing_embedder import embed_text
from autopilot_platform.platform.rag.keyword_retriever import retrieve_keyword
from autopilot_platform.platform.rag.similarity import cosine
from autopilot_platform.platform.rag.vector_retriever import retrieve_vector


def test_hashing_embed_normalized():
    v = embed_text("登录 密码 校验")
    assert len(v) == 256
    assert abs(sum(x * x for x in v) - 1.0) < 1e-6


def test_cosine_identical():
    a = embed_text("用户登录成功")
    assert cosine(a, a) > 0.99


def test_vector_retriever_ranks_related():
    rows = [
        SimpleNamespace(
            id="1",
            title="登录流程",
            content="用户输入账号密码后进入首页",
            category="auth",
            confirmed=True,
        ),
        SimpleNamespace(
            id="2",
            title="支付退款",
            content="订单完成后申请退款到原支付渠道",
            category="pay",
            confirmed=True,
        ),
    ]
    hits = retrieve_vector(rows, query="账号密码登录首页", top_k=2)
    assert hits
    assert hits[0].id == "1"


def test_keyword_retriever_still_works():
    rows = [
        SimpleNamespace(
            id="1",
            title="登录",
            content="密码错误提示",
            category="",
            confirmed=False,
        ),
    ]
    hits = retrieve_keyword(rows, query="登录密码", top_k=3)
    assert hits and hits[0].id == "1"
