"""从 result.json 提取失败意图，供「人只审失败」视图使用。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def failed_intent_steps_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """滤出 binding_hit=failed 或 FAIL 且带 intent_id 的步骤。"""
    out: list[dict[str, Any]] = []
    if not isinstance(result, dict):
        return out
    for case in result.get("cases") or []:
        if not isinstance(case, dict):
            continue
        case_name = str(case.get("name") or "")
        rel = str(case.get("relative_path") or "")
        lid = str(case.get("logical_case_id") or "")
        for step in case.get("steps") or []:
            if not isinstance(step, dict):
                continue
            iid = str(step.get("intent_id") or "").strip()
            hit = str(step.get("binding_hit") or "").strip().lower()
            status = str(step.get("status") or "").upper()
            failed = hit == "failed" or (iid and status == "FAIL")
            if not failed:
                continue
            out.append(
                {
                    "logical_case_id": lid,
                    "case_name": case_name,
                    "relative_path": rel,
                    "intent_id": iid or "",
                    "name": str(step.get("name") or ""),
                    "status": status,
                    "binding_hit": hit or "failed",
                    "heal_applied": bool(step.get("heal_applied")),
                    "fail_reason": str(step.get("fail_reason") or ""),
                    "fail_reason_label": str(step.get("fail_reason_label") or ""),
                    "rolled_back": bool(step.get("rolled_back")),
                    "error_message": str(
                        step.get("error_message") or case.get("error_message") or ""
                    )[:500],
                }
            )
    return out


def load_result_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def find_latest_result_json(project_dir: str | Path) -> Path | None:
    root = Path(project_dir)
    candidates: list[Path] = []
    latest = root / "reports" / "result_latest.json"
    if latest.is_file():
        candidates.append(latest)
    reports = root / "reports"
    if reports.is_dir():
        for p in reports.rglob("result.json"):
            if p.is_file():
                candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def collect_failed_intents(
    project_dir: str | Path,
    *,
    result_path: str | Path | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    """返回 (result 路径, 失败意图列表)；附带 Binding 的 heal/候选摘要。"""
    from ..mgmt.binding_coverage import enrich_failed_row_with_binding

    path: Path | None
    if result_path:
        path = Path(result_path)
        if not path.is_file():
            return path, []
    else:
        path = find_latest_result_json(project_dir)
        if path is None:
            return None, []
    try:
        result = load_result_json(path)
    except (OSError, json.JSONDecodeError):
        return path, []
    rows = failed_intent_steps_from_result(result)
    enriched = [
        enrich_failed_row_with_binding(r, project_dir=project_dir) for r in rows
    ]
    return path, enriched
