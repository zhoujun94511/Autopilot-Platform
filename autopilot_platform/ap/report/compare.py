"""用例级报告对比：新增失败 / 已修复 / 仍失败（纯函数，IDE 与平台共用）。"""

from __future__ import annotations

from typing import Any

_ID_KEYS = (
    "logical_case_id",
    "case_key",
    "automation_case_id",
    "relative_path",
    "name",
)


def case_identity(case: dict[str, Any] | None) -> str:
    """对齐键：logical_case_id > case_key > automation_case_id > 相对路径 > 名称。"""
    if not isinstance(case, dict):
        return ""
    for key in _ID_KEYS:
        val = str(case.get(key) or "").strip()
        if val:
            return f"{key}:{val}"
    return ""


def normalize_case_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in ("passed", "pass", "ok", "success", "succeeded"):
        return "passed"
    if text in ("failed", "fail", "error", "errored"):
        return "failed"
    return text or "unknown"


def _case_brief(case: dict[str, Any], *, side: str) -> dict[str, Any]:
    cls = str(case.get("fail_class") or "").strip()
    label = str(case.get("fail_class_label") or "").strip()
    err = str(case.get("error_message") or "").strip()
    return {
        "key": case_identity(case),
        "name": str(case.get("name") or ""),
        "status": normalize_case_status(case.get("status")),
        "fail_class": cls,
        "fail_class_label": label,
        "error_message": err[:240],
        "side": side,
    }


def _pair_brief(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    src = right or left or {}
    item = {
        "key": case_identity(src),
        "name": str(src.get("name") or (left or {}).get("name") or ""),
        "left_status": normalize_case_status((left or {}).get("status")) if left else "",
        "right_status": normalize_case_status((right or {}).get("status")) if right else "",
        "fail_class": str(
            (right or {}).get("fail_class") or (left or {}).get("fail_class") or ""
        ),
        "fail_class_label": str(
            (right or {}).get("fail_class_label")
            or (left or {}).get("fail_class_label")
            or ""
        ),
        "error_message": str(
            (right or {}).get("error_message") or (left or {}).get("error_message") or ""
        )[:240],
    }
    return item


def compare_case_lists(
    left_cases: list[Any] | None,
    right_cases: list[Any] | None,
) -> dict[str, Any]:
    """对比两侧 result.json cases[]。

    返回 new_fail / fixed / still_fail / only_left / only_right 与 counts。
    """
    left_map: dict[str, dict[str, Any]] = {}
    right_map: dict[str, dict[str, Any]] = {}
    for raw in left_cases or []:
        if not isinstance(raw, dict):
            continue
        key = case_identity(raw)
        if key:
            left_map[key] = raw
    for raw in right_cases or []:
        if not isinstance(raw, dict):
            continue
        key = case_identity(raw)
        if key:
            right_map[key] = raw

    new_fail: list[dict[str, Any]] = []
    fixed: list[dict[str, Any]] = []
    still_fail: list[dict[str, Any]] = []
    only_left: list[dict[str, Any]] = []
    only_right: list[dict[str, Any]] = []

    for key, left in left_map.items():
        right = right_map.get(key)
        ls = normalize_case_status(left.get("status"))
        if right is None:
            only_left.append(_case_brief(left, side="left"))
            continue
        rs = normalize_case_status(right.get("status"))
        if ls == "passed" and rs == "failed":
            new_fail.append(_pair_brief(left, right))
        elif ls == "failed" and rs == "passed":
            fixed.append(_pair_brief(left, right))
        elif ls == "failed" and rs == "failed":
            still_fail.append(_pair_brief(left, right))

    for key, right in right_map.items():
        if key in left_map:
            continue
        only_right.append(_case_brief(right, side="right"))
        if normalize_case_status(right.get("status")) == "failed":
            new_fail.append(_pair_brief(None, right))

    counts = {
        "new_fail": len(new_fail),
        "fixed": len(fixed),
        "still_fail": len(still_fail),
        "only_left": len(only_left),
        "only_right": len(only_right),
        "left": len(left_map),
        "right": len(right_map),
    }
    return {
        "new_fail": new_fail,
        "fixed": fixed,
        "still_fail": still_fail,
        "only_left": only_left,
        "only_right": only_right,
        "counts": counts,
    }


def refine_verdict(summary_verdict: str, case_diff: dict[str, Any] | None) -> str:
    """有用例级数据时，用 new_fail / fixed 修正汇总结论。"""
    counts = (case_diff or {}).get("counts") if isinstance(case_diff, dict) else None
    if not isinstance(counts, dict):
        return summary_verdict
    n_new = int(counts.get("new_fail") or 0)
    n_fix = int(counts.get("fixed") or 0)
    if n_new and n_fix:
        return "mixed"
    if n_new and not n_fix:
        return "regressed"
    if n_fix and not n_new:
        return "improved"
    return summary_verdict
