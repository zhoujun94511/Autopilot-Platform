"""写出结构化 result.json（平台解析真源；HTML 仍为人读产物）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# noinspection SpellCheckingInspection
def write_result_json(
    path: str,
    *,
    job_id: str,
    status: str,
    suite_name: str,
    passed: int,
    failed: int,
    total: int,
    duration_ms: int,
    summary: str = "",
    artifact_id: str = "",
    app_build_id: str = "",
    project_id: str = "",
    platform: str = "",
    backend_mode: str = "",
    device_udids: list[str] | None = None,
    runner_id: str = "",
    html_report_path: str = "",
    cases: list[dict[str, Any]] | None = None,
    runtime_version: str = "",
) -> str:
    payload = {
        "schema_version": "1.0",
        "job_id": job_id,
        "execution_id": job_id,
        "status": status,
        "artifact_id": artifact_id or None,
        "app_build_id": app_build_id or None,
        "project_id": project_id or None,
        "runtime_version": runtime_version or None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform,
            "backend_mode": backend_mode,
            "device_udids": list(device_udids or []),
            "runner_id": runner_id or None,
        },
        "suite": {
            "name": suite_name,
            "passed": int(passed),
            "failed": int(failed),
            "total": int(total),
            "duration_ms": int(duration_ms),
            "summary": summary,
        },
        "cases": list(cases or []),
        "attachments": [],
        "html_report_path": html_report_path or None,
    }
    # drop nulls at top-level optional fields for cleaner files
    clean = {k: v for k, v in payload.items() if v is not None}
    clean["environment"] = {k: v for k, v in payload["environment"].items() if v not in (None, [])}
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return os.path.abspath(path)


def _trace_fields_from_path(source_path: str) -> dict[str, str]:
    path = (source_path or "").strip()
    if not path or not path.lower().endswith((".yaml", ".yml")):
        return {}
    try:
        # noinspection PyUnresolvedReferences
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, ImportError, AttributeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("logical_case_id", "automation_case_id", "case_key"):
        val = str(data.get(key) or "").strip()
        if val:
            out[key] = val
    return out


def cases_from_suite(suite: Any, *, project_dir: str = "") -> list[dict[str, Any]]:
    """SuiteResult → result.v1 cases[]（含 intent 步进字段，对齐 IDE report）。"""
    root = os.path.abspath(project_dir) if project_dir else ""
    out: list[dict[str, Any]] = []
    case_results = list(getattr(suite, "results", None) or [])
    for case_result in case_results:
        item: dict[str, Any] = {
            "name": str(getattr(case_result, "case_name", "") or ""),
            "status": "passed" if bool(getattr(case_result, "passed", False)) else "failed",
            "duration_ms": int(getattr(case_result, "duration_ms", 0) or 0),
        }
        source_path = str(getattr(case_result, "source_path", "") or "").strip()
        relative_path = source_path
        if source_path:
            if root:
                try:
                    relative_path = os.path.relpath(source_path, root).replace("\\", "/")
                except ValueError:
                    relative_path = source_path.replace("\\", "/")
            item["relative_path"] = relative_path
            item.update(_trace_fields_from_path(source_path))
        step_rows: list[dict[str, Any]] = []
        for step_result in getattr(case_result, "results", None) or []:
            row: dict[str, Any] = {
                "name": str(
                    getattr(step_result, "comment", "")
                    or getattr(step_result, "keyword_id", "")
                    or ""
                ),
                "status": str(getattr(step_result, "status", "") or ""),
            }
            iid = str(getattr(step_result, "intent_id", "") or "")
            if iid:
                row["intent_id"] = iid
            hit = str(getattr(step_result, "binding_hit", "") or "")
            if hit:
                row["binding_hit"] = hit
            if bool(getattr(step_result, "heal_applied", False)):
                row["heal_applied"] = True
            rkw = str(getattr(step_result, "resolved_keyword_id", "") or "")
            if rkw:
                row["resolved_keyword_id"] = rkw
            fr = str(getattr(step_result, "fail_reason", "") or "")
            if fr:
                row["fail_reason"] = fr
                row["fail_reason_label"] = str(
                    getattr(step_result, "fail_reason_label", "") or ""
                )
            if bool(getattr(step_result, "rolled_back", False)):
                row["rolled_back"] = True
            msg = str(getattr(step_result, "message", "") or "")
            if getattr(step_result, "status", "") == "FAIL" and msg:
                row["error_message"] = msg[:500]
                if "error_message" not in item:
                    item["error_message"] = msg[:500]
            if iid or hit or getattr(step_result, "status", "") == "FAIL":
                step_rows.append(row)
        if step_rows:
            item["steps"] = step_rows
        if source_path:
            try:
                from .binding_evidence import attach_status_evidence

                attach_status_evidence(
                    item,
                    source_path=source_path,
                    project_dir=root,
                    passed=bool(getattr(case_result, "passed", False)),
                )
            except Exception as exc:  # noqa: BLE001  证据失败不影响 result.json 主结构
                logger.warning(
                    "attach_status_evidence failed case=%s: %s",
                    item.get("name") or source_path,
                    exc,
                )
        out.append(item)
    return out
