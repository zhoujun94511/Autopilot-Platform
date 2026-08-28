"""APPROVED 意图用例轮询拉取状态。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def seen_state_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / ".autopilot" / "intent_import_seen.json"


def load_seen_ids(project_dir: str | Path) -> set[str]:
    path = seen_state_path(project_dir)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("logical_case_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        return set()
    return {str(x).strip() for x in ids if str(x).strip()}


def save_seen_ids(project_dir: str | Path, ids: set[str]) -> Path:
    path = seen_state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"logical_case_ids": sorted(ids)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def filter_new_cases(
    cases: list[dict[str, Any]],
    seen: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("logical_case_id") or case.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        out.append(case)
    return out
