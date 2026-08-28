"""从本地 `.tc.yaml` 提取逻辑用例追踪信息。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_tc_yaml(source_path: str) -> dict[str, Any] | None:
    path = (source_path or "").strip()
    if not path or not path.lower().endswith((".yaml", ".yml")):
        return None
    try:
        # noinspection PyUnresolvedReferences
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def logical_case_id_from_path(source_path: str) -> str:
    data = load_tc_yaml(source_path)
    if not data:
        return ""
    return str(data.get("logical_case_id") or "").strip()


def _iter_step_nodes(data: dict[str, Any]):
    shells = data.get("shells")
    if not isinstance(shells, dict):
        return
    for key in ("before", "case", "after", "fault"):
        steps = shells.get(key) or []
        if not isinstance(steps, list):
            continue
        for node in steps:
            if isinstance(node, dict):
                yield node


def has_mapping_required(source_path: str) -> bool:
    """用例步骤 remark 仍含 mapping_required（未完成 Inspector 映射）。"""
    data = load_tc_yaml(source_path)
    if not data:
        return False
    for node in _iter_step_nodes(data):
        remark = str(node.get("remark") or "")
        if "mapping_required" in remark:
            return True
    return False
