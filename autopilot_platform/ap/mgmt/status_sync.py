"""向 Platform 回写逻辑用例 automation_status（尽力而为，不阻断主流程）。"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def collect_logical_case_ids(cases: Iterable[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("logical_case_id") or case.get("id") or "").strip()
        if cid and cid not in seen:
            seen.add(cid)
            ids.append(cid)
    return ids


def collect_logical_ids_from_project(project_dir: str) -> list[str]:
    """扫描工程内 .tc.yaml 的 logical_case_id。"""
    from pathlib import Path

    # noinspection PyUnresolvedReferences
    import yaml

    root = Path(project_dir)
    if not root.is_dir():
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for path in root.rglob("*.tc.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        cid = str(data.get("logical_case_id") or "").strip()
        if cid and cid not in seen:
            seen.add(cid)
            ids.append(cid)
    return ids


def patch_automation_status(
    client: Any,
    case_ids: Iterable[str],
    status: str,
) -> tuple[int, int]:
    """批量 PATCH；返回 (ok, failed)。"""
    ok = failed = 0
    for cid in case_ids or []:
        cid = str(cid or "").strip()
        if not cid:
            continue
        try:
            client.set_automation_status(cid, status)
            ok += 1
        except (OSError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:
            failed += 1
            code = int(getattr(exc, "status_code", 0) or 0)
            if code == 403:
                logger.warning(
                    "automation_status patch forbidden id=%s: %s", cid, exc
                )
            else:
                logger.debug("automation_status patch failed id=%s: %s", cid, exc)
    return ok, failed
