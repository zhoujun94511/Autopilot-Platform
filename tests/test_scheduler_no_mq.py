"""AUD-2026-13：调度无独立 MQ — RISK ACCEPTED；禁止静默引入硬依赖。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "architecture" / "ADR_scheduler_no_mq.md"
PYPROJECT = ROOT / "pyproject.toml"
OPS = ROOT / "autopilot_platform" / "platform" / "ops"

# 独立 broker / worker 框架：不得成为 Platform 硬依赖
_FORBIDDEN_DEP_NEEDLES = (
    "celery",
    "dramatiq",
    "huey",
    "rq",
    "arq",
    "kombu",
    "pika",
    "aio-pika",
    "kafka-python",
    "confluent-kafka",
)

_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "celery",
        "dramatiq",
        "huey",
        "rq",
        "arq",
        "kombu",
        "pika",
        "aio_pika",
        "kafka",
        "confluent_kafka",
    }
)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_adr_scheduler_no_mq_risk_accepted():
    assert ADR.is_file()
    text = ADR.read_text(encoding="utf-8")
    assert "AUD-2026-13" in text
    assert "RISK ACCEPTED" in text
    assert "ops_locks" in text or "scheduler_lock" in text


def test_pyproject_has_no_mq_hard_dependency():
    body = PYPROJECT.read_text(encoding="utf-8").lower()
    # 仅扫 [project] 主依赖块，避免误伤注释/文档字符串
    main = body.split("[project.optional-dependencies]", 1)[0]
    hits = [n for n in _FORBIDDEN_DEP_NEEDLES if n in main]
    # "rq" 可能是子串；要求整词
    refined: list[str] = []
    for n in hits:
        if n == "rq":
            if "rq>" in main or "rq=" in main or '"rq"' in main or "'rq'" in main:
                refined.append(n)
        else:
            refined.append(n)
    assert not refined, f"禁止将 MQ 列为硬依赖（AUD-2026-13）: {refined}"


def test_scheduler_ops_do_not_import_mq():
    violations: list[str] = []
    for path in sorted(OPS.glob("scheduler_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hit = _imported_roots(tree) & _FORBIDDEN_IMPORT_ROOTS
        if hit:
            violations.append(f"{path.name}: {sorted(hit)}")
    assert not violations, violations


def test_schedule_loop_uses_db_lease_not_broker():
    src = (OPS / "scheduler_loop.py").read_text(encoding="utf-8")
    assert "try_acquire_scheduler_lease" in src
    assert "start_schedule_loop" in src
    assert "MC_SCHEDULE_ENABLED" in src
    lock = (OPS / "scheduler_lock.py").read_text(encoding="utf-8")
    assert "SCHEDULER_LOCK_NAME" in lock
    assert "schedule_loop" in lock
