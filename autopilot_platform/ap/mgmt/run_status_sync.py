"""本地跑完后按结果回写 automation_status。

- 通过且 Binding 覆盖完整 → EXECUTABLE
- 通过但部分意图未固化 Binding → BINDING_PARTIAL
- 失败且仍有 mapping_required（遗留）→ MAPPING_REQUIRED
- 失败（意图/绑定路径）→ DEBUGGING（人审入口）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .binding_coverage import status_for_passed_case
from .case_trace import has_mapping_required, logical_case_id_from_path

logger = logging.getLogger(__name__)

_STATUS_KEYS = (
    "EXECUTABLE",
    "BINDING_PARTIAL",
    "PENDING_VERIFY",
    "DEBUGGING",
    "MAPPING_REQUIRED",
)


def _project_dir_from_suite(suite: Any) -> str | None:
    for rr in getattr(suite, "results", None) or []:
        path = str(getattr(rr, "source_path", "") or "").strip()
        if not path:
            continue
        p = Path(path).resolve()
        if p.is_file():
            parent = p.parent
            if parent.name in ("imported_logical", "testcases", "cases"):
                return str(parent.parent)
            return str(parent)
    return None


def collect_status_targets(
    suite: Any,
    *,
    project_dir: str | None = None,
) -> dict[str, list[str]]:
    """按目标状态分组 logical_case_id。

    同一 id 只出现一次；失败优先于通过；
    优先级：MAPPING_REQUIRED > DEBUGGING > PENDING_VERIFY > BINDING_PARTIAL > EXECUTABLE
    """
    buckets: dict[str, list[str]] = {k: [] for k in _STATUS_KEYS}
    chosen: dict[str, str] = {}
    priority = {
        "EXECUTABLE": 1,
        "BINDING_PARTIAL": 2,
        "PENDING_VERIFY": 3,
        "DEBUGGING": 4,
        "MAPPING_REQUIRED": 5,
    }
    root = project_dir or _project_dir_from_suite(suite)

    for rr in getattr(suite, "results", None) or []:
        path = str(getattr(rr, "source_path", "") or "")
        cid = logical_case_id_from_path(path)
        if not cid:
            continue
        if bool(getattr(rr, "passed", False)):
            status = status_for_passed_case(
                tc_path=path,
                logical_case_id=cid,
                project_dir=root,
            )
            if status in ("EXECUTABLE", "BINDING_PARTIAL") and _suite_case_missing_verification(rr):
                status = "PENDING_VERIFY"
        elif has_mapping_required(path):
            status = "MAPPING_REQUIRED"
        else:
            status = "DEBUGGING"
        prev = chosen.get(cid)
        if prev is None or priority[status] >= priority[prev]:
            chosen[cid] = status

    for cid, status in chosen.items():
        buckets.setdefault(status, []).append(cid)
    return buckets


def _suite_case_missing_verification(rr: Any) -> bool:
    for sr in getattr(rr, "results", None) or []:
        iid = str(getattr(sr, "intent_id", "") or "")
        hit = str(getattr(sr, "binding_hit", "") or "")
        if not (iid or hit):
            continue
        if str(getattr(sr, "status", "") or "") != "PASS":
            continue
        if str(getattr(sr, "verification_status", "") or "") == "missing":
            return True
    return False


def collect_logical_ids_by_outcome(suite: Any) -> tuple[list[str], list[str]]:
    """兼容旧接口：返回 (passed_ids, failed_ids)。"""
    targets = collect_status_targets(suite)
    passed = (
        list(targets.get("EXECUTABLE") or [])
        + list(targets.get("BINDING_PARTIAL") or [])
        + list(targets.get("PENDING_VERIFY") or [])
    )
    failed = list(targets.get("DEBUGGING") or []) + list(
        targets.get("MAPPING_REQUIRED") or []
    )
    return passed, failed


def collect_passed_logical_ids(suite: Any) -> list[str]:
    return collect_logical_ids_by_outcome(suite)[0]


def collect_failed_logical_ids(suite: Any) -> list[str]:
    return collect_logical_ids_by_outcome(suite)[1]


def sync_statuses_after_run(
    suite: Any,
    *,
    client: Any | None = None,
    log: Callable[[str], None] | None = None,
    project_dir: str | None = None,
) -> dict[str, tuple[int, int]]:
    """回写各 automation_status。返回 {status: (ok, failed)}。"""
    from .status_sync import patch_automation_status

    targets = collect_status_targets(suite, project_dir=project_dir)
    out: dict[str, tuple[int, int]] = {k: (0, 0) for k in _STATUS_KEYS}
    total = sum(len(v) for v in targets.values())
    if client is None:
        if log and total:
            parts = " / ".join(f"{k} {len(targets.get(k) or [])}" for k in _STATUS_KEYS)
            log(f"跳过状态回写（未登录管理台）：{parts}")
        return out

    for status, ids in targets.items():
        if not ids:
            continue
        ok, bad = patch_automation_status(client, ids, status)
        out[status] = (ok, bad)
        if log:
            log(
                f"automation_status→{status}：成功 {ok}/{len(ids)}"
                + (f"，失败 {bad}" if bad else "")
            )
    return out


def try_sync_run_statuses_with_session(
    suite: Any,
    *,
    log: Callable[[str], None] | None = None,
    project_dir: str | None = None,
) -> dict[str, tuple[int, int]]:
    """有用户会话则回写通过/失败状态；否则跳过。"""
    from .client import MgmtClientError

    empty = {k: (0, 0) for k in _STATUS_KEYS}
    try:
        from ..runtime import settings

        if not settings.mc_server_url():
            if log:
                log("跳过状态回写（未配置管理台）")
            return empty
        if not settings.mc_project_id():
            if log:
                log("跳过状态回写（未选择管理台项目空间）")
            return empty
        has_user = bool(
            settings.mc_jwt() or (settings.mc_username() and settings.mc_password())
        )
        if not has_user:
            if log:
                log("跳过状态回写（无管理台用户会话）")
            return empty
        from .auth_api import ensure_user_session

        client, _ = ensure_user_session(require=False)
    except (MgmtClientError, Exception) as exc:  # noqa: BLE001
        logger.debug("ensure_user_session skipped: %s", exc)
        if log:
            log("跳过状态回写（无可用管理台会话）")
        return empty
    if client is None:
        if log:
            log("跳过状态回写（无管理台会话）")
        return empty
    try:
        out = sync_statuses_after_run(
            suite, client=client, log=log, project_dir=project_dir
        )
        failed_n = sum(int(b or 0) for _, b in (out or {}).values())
        if failed_n and log:
            log(
                f"状态回写有 {failed_n} 条失败（若为 403，请确认当前账号是项目成员）"
            )
        return out
    finally:
        try:
            client.close()
        except (OSError, RuntimeError, AttributeError, TypeError):
            pass
