"""从 Platform 导出的逻辑/意图用例生成 AutoPilot `.tc.yaml`（默认可跑 intent_act）。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

# noinspection PyUnresolvedReferences
import yaml

from ..intent.bindings import ensure_empty_binding
from ..intent.normalize import logical_texts_to_intent_steps, normalize_intent_steps


def _safe_filename(title: str, case_key: str) -> str:
    base = (case_key or title or "case").strip()
    base = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", base).strip("._") or "case"
    return f"{base[:80]}.tc.yaml"


def _intent_step_nodes(
    intent_steps: list[dict[str, Any]],
    *,
    logical_case_id: str = "",
    revision_id: str = "",
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for step in intent_steps:
        sid = str(step.get("id") or "").strip() or f"s{len(nodes) + 1}"
        action = str(step.get("action") or "custom").strip()
        target = str(step.get("target") or "").strip()
        value = str(step.get("value") or "").strip()
        text = str(step.get("text") or target or sid).strip()
        params: dict[str, str] = {
            "intent_id": sid,
            "action": action,
            "target": target,
            "value": value,
            "text": text,
        }
        channel = str(step.get("channel") or "").strip().lower()
        if channel in ("ui", "http", "auto"):
            params["channel"] = channel
        if logical_case_id:
            params["logical_case_id"] = logical_case_id
        if revision_id:
            params["revision_id"] = revision_id
        nodes.append(
            {
                "step": "intent_act",
                "comment": text,
                "remark": f"intent:{sid}|{action}",
                "is_run": True,
                "params": params,
            }
        )
    if not nodes:
        nodes.append(
            {
                "step": "intent_act",
                "comment": "（空意图，请补充）",
                "remark": "intent:s1|custom",
                "is_run": True,
                "params": {
                    "intent_id": "s1",
                    "action": "custom",
                    "target": "",
                    "value": "",
                    "text": "（空意图，请补充）",
                    "logical_case_id": logical_case_id,
                },
            }
        )
    return nodes


def _session_shells(session: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """根据目标应用参数生成 before/after；返回 (before, after, platform)。"""
    if not session:
        return [], [], ""
    pkg = str(session.get("package_name") or session.get("packageName") or "").strip()
    if not pkg:
        return [], [], ""
    plat = str(session.get("platform") or "android").strip().lower()
    typ = str(session.get("type") or ("Android" if plat == "android" else "iOS")).strip()
    params: dict[str, str] = {"type": typ, "packageName": pkg}
    act = str(session.get("main_activity") or session.get("activityName") or session.get("activity") or "").strip()
    if act:
        params["activityName"] = act
    before = [
        {"step": "appium_start", "comment": "确保 Appium 就绪", "is_run": True},
        {
            "step": "mobile_app_start",
            "comment": f"打开目标应用 {pkg}",
            "is_run": True,
            "params": params,
        },
    ]
    after = [{"step": "mobile_app_close", "comment": "关闭会话", "is_run": True}]
    return before, after, plat


def logical_case_to_tc_dict(
    case: dict[str, Any],
    *,
    project_id: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    logical_id = str(case.get("logical_case_id") or case.get("id") or "").strip()
    automation_id = uuid.uuid4().hex
    title = str(case.get("title") or "imported_case").strip()
    revision_id = str(case.get("revision_id") or uuid.uuid4().hex)
    raw_intents = case.get("intent_steps")
    if isinstance(raw_intents, list) and raw_intents and isinstance(raw_intents[0], dict):
        intent_steps = normalize_intent_steps(raw_intents)
    else:
        steps = case.get("logical_steps") or case.get("steps") or []
        expected = case.get("expected_results") or case.get("expected") or []
        intent_steps = logical_texts_to_intent_steps(
            [str(x) for x in steps],
            [str(x) for x in expected],
        )
    pre = case.get("preconditions") or []
    if isinstance(pre, str):
        pre_list = [pre]
    else:
        pre_list = [str(x) for x in (pre or []) if str(x).strip()]

    desc = {
        "description": str(case.get("description") or ""),
        "precondition": "；".join(pre_list),
    }
    before, after, plat = _session_shells(session)
    return {
        "type": "testcase",
        "format_version": 2,
        "schema_version": "2.0",
        "project_id": project_id or str(case.get("project_id") or ""),
        "logical_case_id": logical_id,
        "automation_case_id": automation_id,
        "revision_id": revision_id,
        "case_key": str(case.get("case_key") or ""),
        "name": title,
        "data_id": automation_id[:12],
        "tag": "INTENT",
        "platform": plat,
        "is_execute": True,
        "able_invoked": False,
        "datapool": "DATATABLE(NONE,false)",
        "desc": {k: v for k, v in desc.items() if v},
        "shells": {
            "before": before,
            "case": _intent_step_nodes(
                intent_steps, logical_case_id=logical_id, revision_id=revision_id
            ),
            "after": after,
            "fault": [],
        },
    }


def write_logical_cases_as_drafts(
    project_dir: str | Path,
    cases: list[dict[str, Any]],
    *,
    project_id: str = "",
    subdir: str = "imported_logical",
    session: dict[str, Any] | None = None,
) -> list[Path]:
    """把意图用例写入工程目录（可跑），并初始化空 Binding 文件。

    ``session`` 可选：目标应用参数（platform/package_name[/main_activity]），
    写入后自动补齐 appium_start + mobile_app_start / mobile_app_close。
    """
    root = Path(project_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"工程目录不存在: {root}")
    out_dir = root / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        data = logical_case_to_tc_dict(case, project_id=project_id, session=session)
        name = _safe_filename(str(data.get("name") or ""), str(data.get("case_key") or ""))
        path = out_dir / name
        if path.exists():
            path = out_dir / f"{path.stem}_{data['automation_case_id'][:8]}{path.suffix}"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        lid = str(data.get("logical_case_id") or "").strip()
        if lid:
            ensure_empty_binding(
                root, lid, revision_id=str(data.get("revision_id") or "")
            )
        written.append(path)
    return written
