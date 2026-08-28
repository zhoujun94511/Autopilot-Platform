"""Services 领域拆包后的导入契约与调用链路白盒。

覆盖：
- 顶层 facade 不再导出业务符号
- 旧扁平模块 / 旧 monkeypatch 路径已消失
- API、调度器、跨域桥接到真源且符号齐全
- 子包均可 import（引用缺失会在收集期暴露）
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "autopilot_platform" / "platform"
SERVICES = PLATFORM / "services"

# 已删除的扁平模块；新路径带 execution/design/remote 等前缀，扫描时必须排除。
_REMOVED_FLAT = (
    "devices",
    "jobs",
    "runners",
    "schedules",
    "resource_pools",
    "managed_runner",
    "device_reservations",
    "device_remote",
    "device_remote_hub",
    "fleet_alerts",
    "job_quality",
    "agentops",
    "organizations",
    "project_invites",
    "rbac",
    "session_tokens",
    "refresh_cookie",
    "ide_handoff",
    "public_bootstrap",
    "turn_health",
    "_common",
    "design_list_query",
    "design_chat",
    "design_documents",
    "design_access",
    "design_activity",
    "design_enqueue",
    "design_stats",
    "design_export",
    "design_knowledge",
    "design_requirements",
    "report_compare",
)

_REMOVED_FILES = ("design.py", "design_chat.py", "design_documents.py")

_FLAT_ALT = "|".join(_REMOVED_FLAT)
_OLD_ABS = re.compile(
    rf"\bautopilot_platform\.platform\.services\.({_FLAT_ALT})\b"
)
_OLD_REL = re.compile(
    rf"from\s+\.+services\.({_FLAT_ALT})\b"
)
_OLD_FROM_PKG = re.compile(
    rf"from\s+autopilot_platform\.platform\.services\s+import\s+\(?\s*({_FLAT_ALT})\b"
)
_OLD_REL_FROM_PKG = re.compile(
    rf"from\s+\.+services\s+import\s+\(?\s*({_FLAT_ALT})\b"
)

_SKIP_DIRS = {"__pycache__", "archive", "frontend", "node_modules"}

_API_SYMBOLS: dict[str, tuple[str, ...]] = {
    "autopilot_platform.platform.services.execution.jobs": (
        "create_job",
        "list_jobs",
        "claim_job",
        "claim_job_wait",
        "mark_job_running",
        "nack_job",
        "complete_job",
        "cancel_job",
        "retry_job",
        "append_job_log",
        "read_job_log",
        "read_job_log_since",
        "job_is_terminal",
        "reclaim_stale_jobs",
    ),
    "autopilot_platform.platform.services.reports": (
        "store_job_report",
        "resolve_job_report_path",
        "resolve_job_result_json_path",
        "list_job_evidence_files",
        "resolve_job_evidence_file",
        "purge_job_reports",
        "list_reports",
        "compare_reports",
    ),
    "autopilot_platform.platform.services.execution.runners": (
        "register_runner",
        "heartbeat",
        "list_runners",
        "issue_runner_token",
        "get_device_inventory",
        "update_device_selection",
        "deregister_runner",
        "set_runner_scope",
    ),
    "autopilot_platform.platform.services.execution.devices": (
        "list_tr_devices",
        "device_board",
        "release_device",
        "set_device_maintenance",
        "reconcile_orphan_device_busy",
    ),
    "autopilot_platform.platform.services.execution.schedules": (
        "create_schedule",
        "list_schedules",
        "get_schedule",
        "update_schedule",
        "delete_schedule",
        "run_schedule_now",
        "tick_due_schedules",
        "on_job_finished",
    ),
    "autopilot_platform.platform.services.shared": (
        "is_online",
        "job_to_out",
        "runner_to_out",
        "BEST_EFFORT_ERRS",
        "paginate",
        "clamp_page",
    ),
    "autopilot_platform.platform.services.observability": (
        "agentops_snapshot",
        "job_quality_snapshot",
        "tick_fleet_alerts",
    ),
    "autopilot_platform.platform.identity.session_tokens": ("issue_session",),
    "autopilot_platform.platform.tenancy.organizations": ("org_member_role",),
    "autopilot_platform.platform.authz.rbac": ("can",),
}


def _iter_py(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _scan_old_refs(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for rx in (_OLD_ABS, _OLD_REL, _OLD_FROM_PKG, _OLD_REL_FROM_PKG):
            for m in rx.finditer(text):
                hits.append(f"{rel}: {m.group(0)}")
    return hits


def test_facade_exports_nothing():
    from autopilot_platform.platform import services

    assert list(services.__all__) == []
    for name in ("is_online", "create_job", "heartbeat", "job_to_out"):
        assert not hasattr(services, name), f"facade 仍导出 {name}"


def test_removed_flat_modules_are_gone():
    for name in ("devices", "jobs", "runners", "schedules", "organizations", "rbac", "session_tokens", "_common"):
        assert not (SERVICES / f"{name}.py").exists(), name
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"autopilot_platform.platform.services.{name}")
    for name in _REMOVED_FILES:
        assert not (SERVICES / name).exists(), name


def test_production_has_no_old_services_imports():
    hits = _scan_old_refs(_iter_py(PLATFORM))
    assert hits == [], "生产代码仍引用已删除扁平模块:\n" + "\n".join(hits)


def test_tests_have_no_old_services_imports():
    hits = _scan_old_refs(_iter_py(ROOT / "tests"))
    assert hits == [], "测试仍引用已删除扁平模块:\n" + "\n".join(hits)


def test_true_source_packages_import_and_export_api_symbols():
    for mod_name, names in _API_SYMBOLS.items():
        mod = importlib.import_module(mod_name)
        missing = [n for n in names if not hasattr(mod, n)]
        assert not missing, f"{mod_name} 缺少 {missing}"


def test_all_service_submodules_import():
    pkg = importlib.import_module("autopilot_platform.platform.services")
    failed: list[str] = []
    for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001 — 白盒要列出真实导入失败
            failed.append(f"{info.name}: {type(exc).__name__}: {exc}")
    assert not failed, "子模块导入失败:\n" + "\n".join(failed)


def test_scheduler_loop_binds_true_sources():
    src = (PLATFORM / "ops" / "scheduler_loop.py").read_text(encoding="utf-8")
    assert "services.execution.schedules import tick" in src
    assert "services.execution.jobs.recovery import reclaim_stale_jobs" in src
    assert "services.reports.storage import purge_job_reports" in src
    assert "services.observability.fleet_alerts import tick_fleet_alerts" in src
    assert "from .. import services" not in src
    from autopilot_platform.platform.ops import scheduler_loop

    assert callable(scheduler_loop.start_schedule_loop)


def test_job_complete_calls_schedule_callback_not_facade():
    src = (SERVICES / "execution" / "jobs" / "lifecycle.py").read_text(encoding="utf-8")
    assert "from ..schedules.callbacks import on_job_finished" in src
    assert "from ... import services" not in src
    assert "from .... import services" not in src


def test_design_enqueue_calls_execution_create_job():
    src = (SERVICES / "design" / "enqueue.py").read_text(encoding="utf-8")
    assert "services.execution.jobs.creation import create_job" in src
    from autopilot_platform.platform.services.design import enqueue
    from autopilot_platform.platform.services.execution.jobs.creation import create_job

    assert enqueue.create_job is create_job


def test_api_modules_parse_and_bind_domain_packages():
    """API 层 import 语句必须指向领域包，且 AST 可解析。"""
    expected = {
        "jobs.py": (
            "services.execution import jobs",
            "services import reports",
            "services.shared.mappers import job_to_out",
        ),
        "runners.py": ("services.execution import runners",),
        "devices.py": (
            "services.execution import devices",
            "services.remote import reservations",
        ),
        "schedules.py": ("services.execution import schedules",),
        "resource_pools.py": ("services.execution.resources import pools",),
        "device_remote.py": ("services.remote import sessions",),
        "design.py": (
            "services.design.cases import crud",
            "services.design.cases import generation",
        ),
        "design_chat_routes.py": ("services.design.chat import sessions",),
        "auth.py": ("identity import session_tokens",),
        "public.py": ("ops.public_bootstrap import build_public_bootstrap",),
    }
    for name, needles in expected.items():
        path = PLATFORM / "api" / name
        text = path.read_text(encoding="utf-8")
        ast.parse(text)
        for needle in needles:
            assert needle in text, f"{name} 缺少 {needle}"


def test_identity_tenancy_authz_ops_true_sources_exist():
    for rel in (
        "identity/session_tokens.py",
        "identity/refresh_cookie.py",
        "identity/ide_handoff.py",
        "tenancy/organizations.py",
        "tenancy/project_invites.py",
        "authz/rbac.py",
        "ops/public_bootstrap.py",
        "ops/turn_health.py",
    ):
        assert (PLATFORM / rel).is_file(), rel


def test_docs_record_no_facade_contract():
    api_doc = (ROOT / "docs" / "architecture" / "SERVICES_PUBLIC_API.md").read_text(
        encoding="utf-8"
    )
    layout = (ROOT / "docs" / "architecture" / "PLATFORM_PACKAGE_LAYOUT.md").read_text(
        encoding="utf-8"
    )
    assert "services.__init__" in api_doc
    assert "不提供聚合 facade" in api_doc or "不导入或重新导出" in api_doc
    assert "services.execution" in layout
    assert "services.jobs" in api_doc


def test_create_app_imports_after_facade_removal(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    from autopilot_platform.platform.core.db import reset_engine
    from autopilot_platform.platform.app import create_app

    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'svc.db').as_posix()}")
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/jobs" in paths
    assert "/api/v1/runners/heartbeat" in paths
    assert "/api/v1/devices" in paths
    assert "/api/v1/schedules" in paths
    reset_engine()
