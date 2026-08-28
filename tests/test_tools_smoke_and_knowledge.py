"""tools/smoke_http.py / knowledge CLI 白盒（不要求服务在线）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_smoke_http_module_matrix():
    from tools import smoke_http as m

    assert "core" in m.MODULES and "auth" in m.MODULES
    assert m.SMOKE_ORDER == ["core", "auth", "projects", "jobs"]
    ctx = m.SmokeContext(base_url="http://127.0.0.1:9", user="u", password="p")
    assert "Authorization" not in ctx.headers(auth=True)
    ctx.token = "tok"
    assert ctx.headers()["Authorization"] == "Bearer tok"


def test_batch_import_collect_and_multipart(tmp_path: Path):
    from tools import batch_import_knowledge as m

    d = tmp_path / "kb"
    d.mkdir()
    (d / "a.md").write_text("# hi\nbody", encoding="utf-8")
    (d / "b.txt").write_text("x", encoding="utf-8")
    (d / "skip.bin").write_bytes(b"\x00")
    files = m.collect_files([d], "")
    assert {f.name for f in files} == {"a.md", "b.txt"}
    only = m.collect_files([d], "a.md")
    assert [f.name for f in only] == ["a.md"]

    body, boundary = m.build_multipart(
        project_id="p1",
        category="other",
        confirmed=True,
        description="",
        files=only,
    )
    assert b"project_id" in body
    assert b"a.md" in body
    assert boundary.encode() in body


def test_knowledge_admin_argparse():
    from tools import knowledge_admin as m

    # 无服务：只验证子命令解析
    try:
        m.main(["--project-id", "x"])  # missing subcommand
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code not in (0,)
