"""持久化向量索引冒烟。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot_platform.platform.rag.hashing_embedder_adapter import HashingEmbedder
from autopilot_platform.platform.rag.index_builder import ensure_index_vectors
from autopilot_platform.platform.rag.vector_index_store import (
    invalidate_project_index,
    load_index,
)


def test_ensure_index_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path))
    invalidate_project_index("proj-x")
    rows = [
        SimpleNamespace(
            id="k1",
            title="登录",
            content="账号密码进入首页",
            category="auth",
            confirmed=True,
        )
    ]
    emb = HashingEmbedder()
    vecs1 = ensure_index_vectors("proj-x", rows, emb)
    assert "k1" in vecs1 and len(vecs1["k1"]) == 256
    stored = load_index("proj-x")
    assert stored.get("embedder") == "hashing_v1"
    assert "k1" in (stored.get("items") or {})

    # 二次调用不丢（BLOB float32 往返允许微小量化差）
    vecs2 = ensure_index_vectors("proj-x", rows, emb)
    assert len(vecs2["k1"]) == len(vecs1["k1"])
    assert all(abs(a - b) < 1e-5 for a, b in zip(vecs2["k1"], vecs1["k1"]))
