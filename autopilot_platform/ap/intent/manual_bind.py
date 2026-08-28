"""人审写回 Binding：手动固化 locator / keyword。"""

from __future__ import annotations

from typing import Any

from .bindings import load_binding, upsert_step_binding


_DEFAULT_KW = {
    ("web", "click"): "web_element_click",
    ("web", "type"): "web_element_text_input",
    ("web", "assert"): "web_verify_element_existed",
    ("web", "open"): "web_browser_locate",
    ("web", "wait"): "web_common_sleep",
    ("android", "click"): "mobile_element_click",
    ("android", "type"): "mobile_element_text_input",
    ("android", "assert"): "mobile_verify_element_existed",
    ("android", "swipe"): "mobile_element_swipe",
    ("ios", "click"): "mobile_element_click",
    ("ios", "type"): "mobile_element_text_input",
    ("ios", "assert"): "mobile_verify_element_existed",
    ("ios", "swipe"): "mobile_element_swipe",
}


def default_keyword_id(platform: str, action: str) -> str:
    plat = (platform or "web").strip().lower()
    act = (action or "click").strip().lower()
    if plat not in ("web", "android", "ios"):
        plat = "web"
    return _DEFAULT_KW.get((plat, act)) or _DEFAULT_KW.get((plat, "click")) or "web_element_click"


def apply_manual_binding(
    project_dir: str,
    logical_case_id: str,
    intent_id: str,
    *,
    locator: str,
    keyword_id: str = "",
    platform: str = "web",
    action: str = "click",
    value: str = "",
    resolver: str = "manual",
) -> dict[str, Any]:
    """人工指定定位符并写入 Binding（前置到候选列表）。"""
    lid = (logical_case_id or "").strip()
    iid = (intent_id or "").strip()
    loc = (locator or "").strip()
    if not lid or not iid:
        raise ValueError("logical_case_id / intent_id 不能为空")
    if not loc:
        raise ValueError("locator 不能为空")
    plat = (platform or "web").strip().lower() or "web"
    kid = (keyword_id or "").strip() or default_keyword_id(plat, action)
    params: dict[str, Any] = {"locator": loc}
    if action == "type" and value:
        params["text"] = value
    if action == "open":
        params = {"url": loc}
    if action == "assert" and plat != "web":
        params["outVar"] = "__intent_assert__"

    prev = load_binding(project_dir, lid)
    steps = prev.get("steps") if isinstance(prev.get("steps"), dict) else {}
    old = steps.get(iid) if isinstance(steps.get(iid), dict) else {}
    old_cands = list(old.get("candidates") or []) if isinstance(old, dict) else []
    new_cand = {
        "locator": loc,
        "keyword_id": kid,
        "params": dict(params),
        "score": 1.0,
        "resolver": resolver,
    }
    # 人工候选置顶去重
    merged = [new_cand]
    seen = {f"{kid}|{loc}"}
    for c in old_cands:
        if not isinstance(c, dict):
            continue
        key = f"{c.get('keyword_id')}|{c.get('locator')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)

    return upsert_step_binding(
        project_dir,
        lid,
        iid,
        platform=plat,
        keyword_id=kid,
        params=params,
        candidates=merged,
        resolver=resolver,
        heal_count=int(old.get("heal_count") or 0) if isinstance(old, dict) else 0,
        revision_id=str(prev.get("revision_id") or ""),
    )
