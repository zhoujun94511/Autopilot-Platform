"""从工程 Binding / 用例 YAML 推导 automation_status_evidence（对齐 IDE）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _load_yaml(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file() or not p.suffix.lower() in {".yaml", ".yml"}:
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def count_intent_steps_in_tc(tc_path: str | Path) -> int:
    data = _load_yaml(tc_path)
    if not data:
        return 0
    shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
    case_steps = shells.get("case") if isinstance(shells.get("case"), list) else []
    n = 0
    for step in case_steps:
        if not isinstance(step, dict):
            continue
        kid = str(step.get("step") or step.get("keyword") or "").strip()
        remark = str(step.get("remark") or "")
        if kid == "intent_act" or remark.startswith("intent:"):
            n += 1
    return n


def has_mapping_required(tc_path: str | Path) -> bool:
    data = _load_yaml(tc_path)
    if not data:
        return False
    shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
    for key in ("before", "case", "after", "fault"):
        steps = shells.get(key) if isinstance(shells.get(key), list) else []
        for node in steps:
            if isinstance(node, dict) and "mapping_required" in str(node.get("remark") or ""):
                return True
    return False


def count_bound_steps(project_dir: str | Path, logical_case_id: str) -> int:
    lid = (logical_case_id or "").strip()
    if not lid:
        return 0
    try:
        from autopilot_platform.ap.intent.bindings import load_binding
    except ImportError:
        return 0
    doc = load_binding(project_dir, lid)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    n = 0
    for entry in steps.values():
        if isinstance(entry, dict) and str(entry.get("keyword_id") or "").strip():
            n += 1
    return n


def status_for_passed_case(
    *,
    tc_path: str,
    logical_case_id: str,
    project_dir: str | Path | None = None,
) -> str:
    intent_n = count_intent_steps_in_tc(tc_path)
    if intent_n <= 0:
        return "EXECUTABLE"
    root = Path(project_dir) if project_dir else Path(tc_path).resolve().parent
    if root.name in ("imported_logical", "testcases", "cases"):
        root = root.parent
    bound_n = count_bound_steps(root, logical_case_id)
    if bound_n >= intent_n:
        return "EXECUTABLE"
    return "BINDING_PARTIAL"


def attach_status_evidence(
    item: dict[str, Any],
    *,
    source_path: str,
    project_dir: str,
    passed: bool,
) -> None:
    """就地写入 mapping_required / automation_status_evidence。"""
    logical_case_id = str(item.get("logical_case_id") or "").strip()
    if not source_path or not logical_case_id:
        return
    mapping_required = has_mapping_required(source_path)
    item["mapping_required"] = mapping_required
    if passed:
        item["automation_status_evidence"] = status_for_passed_case(
            tc_path=source_path,
            logical_case_id=logical_case_id,
            project_dir=project_dir or None,
        )
    else:
        item["automation_status_evidence"] = (
            "MAPPING_REQUIRED" if mapping_required else "DEBUGGING"
        )
