"""批次4：dump_ops_config / knowledge_vector_check 白盒。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_dump_ops_filter_category():
    from tools import dump_ops_config as m

    payload = {
        "categories": [
            {"id": "vector_rag", "keys": ["AP_AI_EMBEDDING_MODEL"]},
            {"id": "alerts", "keys": ["AP_ALERT_WEBHOOK"]},
        ],
        "values": {
            "AP_AI_EMBEDDING_MODEL": "x",
            "AP_ALERT_WEBHOOK": "y",
        },
    }
    out = m.filter_by_category(payload, "vector_rag")
    assert len(out["categories"]) == 1
    assert out["categories"][0]["id"] == "vector_rag"
    assert "AP_AI_EMBEDDING_MODEL" in out["values"]
    assert "AP_ALERT_WEBHOOK" not in out["values"]


def test_knowledge_vector_check_summarize_blob(tmp_path: Path):
    from tools import knowledge_vector_check as m
    import struct

    db = tmp_path / "vectors.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE project_meta (
          project_id TEXT PRIMARY KEY,
          embedder TEXT NOT NULL DEFAULT '',
          embedding_dim INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE index_items (
          project_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          content_hash TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL DEFAULT '',
          embedding BLOB,
          PRIMARY KEY (project_id, item_id)
        );
        CREATE VIRTUAL TABLE knowledge_fts USING fts5(
          project_id UNINDEXED, item_id UNINDEXED, content,
          tokenize = 'porter unicode61'
        );
        """
    )
    blob = struct.pack("2f", 0.1, 0.2)
    conn.execute(
        "INSERT INTO project_meta(project_id, embedder, embedding_dim) VALUES('p1','hashing',2)"
    )
    conn.execute(
        "INSERT INTO index_items(project_id, item_id, title, content, embedding) "
        "VALUES('p1','i1','t1','body',?)",
        (blob,),
    )
    conn.execute(
        "INSERT INTO index_items(project_id, item_id, title, content, embedding) "
        "VALUES('p1','i2','t2','',NULL)"
    )
    conn.execute(
        "INSERT INTO knowledge_fts(project_id, item_id, content) VALUES('p1','i1','t1 body')"
    )
    conn.commit()
    summary = m.summarize_index(conn, "p1")
    conn.close()
    assert summary["schema"] == "blob_v2"
    assert summary["total_items"] == 2
    assert summary["empty_vectors"] == 1
    assert summary["fts5"]["available"] is True
    assert summary["fts5"]["rows"] == 1


def test_knowledge_vector_check_compare(tmp_path: Path):
    from tools import knowledge_vector_check as m
    import struct

    vdb = tmp_path / "vectors.sqlite"
    pdb = tmp_path / "platform.db"
    vconn = sqlite3.connect(str(vdb))
    vconn.executescript(
        """
        CREATE TABLE project_meta (
          project_id TEXT PRIMARY KEY,
          embedder TEXT NOT NULL DEFAULT '',
          embedding_dim INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE index_items (
          project_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          content_hash TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL DEFAULT '',
          embedding BLOB,
          PRIMARY KEY (project_id, item_id)
        );
        """
    )
    blob = struct.pack("1f", 1.0)
    vconn.execute(
        "INSERT INTO index_items(project_id, item_id, embedding) VALUES('p1','orphan',?)",
        (blob,),
    )
    vconn.execute(
        "INSERT INTO index_items(project_id, item_id, embedding) VALUES('p1','shared',?)",
        (blob,),
    )
    vconn.commit()

    pconn = sqlite3.connect(str(pdb))
    pconn.execute(
        "CREATE TABLE design_knowledge_items (id TEXT, project_id TEXT, title TEXT)"
    )
    pconn.execute(
        "INSERT INTO design_knowledge_items(id, project_id, title) VALUES('shared','p1','s')"
    )
    pconn.execute(
        "INSERT INTO design_knowledge_items(id, project_id, title) VALUES('missing','p1','m')"
    )
    pconn.commit()
    pconn.close()

    out = m.compare_with_platform_db(vconn, pdb, "p1")
    vconn.close()
    assert out["orphan_in_index_total"] == 1
    assert out["missing_from_index_total"] == 1
    assert out["orphan_in_index"][0]["item_id"] == "orphan"
    assert out["missing_from_index"][0]["item_id"] == "missing"


def test_preflight_mentions_followup_tools():
    text = (ROOT / "tools" / "preflight.py").read_text(encoding="utf-8")
    assert "check_api_contract.py" in text
    assert "smoke_http.py" in text
    assert "knowledge_vector_check.py" in text
    assert "--dry-probe" in text
    assert "web_playwright" in text


def test_preflight_platform_loads_dotenv_for_config(tmp_path, monkeypatch):
    import tools.preflight as pf

    env = tmp_path / ".env"
    env.write_text("MC_JWT_SECRET=test-jwt-from-dotenv\nMC_ADMIN_PASSWORD=strong-secret\n", encoding="utf-8")
    monkeypatch.setattr(pf, "_ROOT", tmp_path)
    monkeypatch.delenv("MC_JWT_SECRET", raising=False)
    monkeypatch.delenv("MC_ADMIN_PASSWORD", raising=False)
    pf._n_warn = 0
    pf._n_fail = 0
    pf.check_platform_config()
    assert "test-jwt-from-dotenv" == __import__("os").environ.get("MC_JWT_SECRET")
