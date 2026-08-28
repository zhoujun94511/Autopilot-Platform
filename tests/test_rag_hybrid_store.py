"""SQLite 向量库：BLOB + FTS5 混合检索。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot_platform.platform.rag.hashing_embedder_adapter import HashingEmbedder
from autopilot_platform.platform.rag.index_builder import ensure_index_vectors
from autopilot_platform.platform.rag.vector_index_store import invalidate_project_index
from autopilot_platform.platform.rag import vector_index_sqlite as store


def test_blob_and_fts_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AP_RAG_HYBRID", "1")
    invalidate_project_index("hyb")
    rows = [
        SimpleNamespace(
            id="login",
            title="登录流程",
            content="用户输入账号密码后进入首页",
            category="auth",
            confirmed=True,
        ),
        SimpleNamespace(
            id="pay",
            title="支付退款",
            content="订单完成后申请退款到原支付渠道",
            category="pay",
            confirmed=True,
        ),
    ]
    emb = HashingEmbedder()
    ensure_index_vectors("hyb", rows, emb)

    loaded = store.load_project("hyb")
    assert loaded["schema_version"] == 2
    assert loaded["items"]["login"]["content"]
    assert loaded["items"]["login"]["vector"]

    import sqlite3

    conn = sqlite3.connect(str(store.db_path()))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM knowledge_fts WHERE project_id=?", ("hyb",)
        ).fetchone()[0]
        assert int(n) == 2
    finally:
        conn.close()

    q = emb.embed_query("账号密码登录")
    hits, engine = store.hybrid_search("hyb", query="账号密码登录", query_vector=q, top_k=2)
    assert hits
    assert hits[0]["id"] == "login"
    assert "vector" in engine or "fts5" in engine or "sqlite_vec" in engine


def test_escape_fts5_special():
    assert store.escape_fts5_query('a"b') == '"a b"'
    assert store.escape_fts5_query("foo AND bar").startswith('"')
    assert store.escape_fts5_query("普通查询") == "普通查询"
