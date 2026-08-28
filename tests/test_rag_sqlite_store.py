"""SQLite 向量索引 roundtrip。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot_platform.platform.rag.hashing_embedder_adapter import HashingEmbedder
from autopilot_platform.platform.rag.index_builder import ensure_index_vectors
from autopilot_platform.platform.rag.vector_index_store import (
    invalidate_project_index,
    load_index,
    remove_index_item,
)
from autopilot_platform.platform.rag import vector_index_sqlite as sqlite_store


def test_sqlite_index_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path))
    invalidate_project_index("proj-s")
    rows = [
        SimpleNamespace(
            id="a1",
            title="登录",
            content="账号密码",
            category="auth",
            confirmed=True,
        )
    ]
    emb = HashingEmbedder()
    vecs = ensure_index_vectors("proj-s", rows, emb)
    assert "a1" in vecs
    assert sqlite_store.db_path().is_file()
    loaded = load_index("proj-s")
    assert loaded["embedder"] == "hashing_v1"
    assert "a1" in loaded["items"]
    remove_index_item("proj-s", "a1")
    loaded2 = load_index("proj-s")
    assert "a1" not in loaded2["items"]
