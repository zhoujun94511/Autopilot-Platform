"""根据用例 intent 步与工程 Binding 覆盖度判断 automation_status 细化态。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def count_intent_steps_in_tc(tc_path: str | Path) -> int:
    """统计 .tc.yaml 中 intent_act 步骤数（含 shells.case）。"""
    path = Path(tc_path)
    if not path.is_file():
        return 0
    try:
        # noinspection PyUnresolvedReferences
        import yaml
    except ImportError:
        return 0
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
        return 0
    if not isinstance(data, dict):
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


def count_bound_steps(project_dir: str | Path, logical_case_id: str) -> int:
    """Binding 中已有 keyword_id 的步数。"""
    from ..intent.bindings import load_binding

    lid = (logical_case_id or "").strip()
    if not lid:
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
    """通过用例：全绑定 → EXECUTABLE；部分 → BINDING_PARTIAL；无意图步 → EXECUTABLE。"""
    intent_n = count_intent_steps_in_tc(tc_path)
    if intent_n <= 0:
        return "EXECUTABLE"
    root = project_dir
    if root is None:
        root = Path(tc_path).resolve().parent
        # 常见：imported_logical/xxx.tc.yaml → 工程根为其父
        if root.name in ("imported_logical", "testcases", "cases"):
            root = root.parent
    bound_n = count_bound_steps(root, logical_case_id)
    if bound_n >= intent_n:
        return "EXECUTABLE"
    if bound_n > 0:
        return "BINDING_PARTIAL"
    # 全绿但未落 Binding（异常或解析未写回）→ 仍标部分绑定，提示需再跑/固化
    return "BINDING_PARTIAL"


def enrich_failed_row_with_binding(
    row: dict[str, Any],
    *,
    project_dir: str | Path,
) -> dict[str, Any]:
    """为人审列表附加 heal_count / 候选摘要。"""
    from ..intent.bindings import load_binding

    out = dict(row)
    lid = str(out.get("logical_case_id") or "").strip()
    iid = str(out.get("intent_id") or "").strip()
    if not lid or not iid:
        return out
    doc = load_binding(project_dir, lid)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    entry = steps.get(iid) if isinstance(steps.get(iid), dict) else None
    if not entry:
        out.setdefault("heal_count", 0)
        out.setdefault("candidates_summary", "")
        return out
    out["heal_count"] = int(entry.get("heal_count") or 0)
    out["keyword_id"] = str(entry.get("keyword_id") or "")
    out["platform"] = str(entry.get("platform") or out.get("platform") or "")
    out["action"] = str(entry.get("action") or out.get("action") or "")
    out["value"] = str(entry.get("value") or out.get("value") or "")
    cands = entry.get("candidates") if isinstance(entry.get("candidates"), list) else []
    bits: list[str] = []
    for c in cands[:3]:
        if not isinstance(c, dict):
            continue
        loc = str(c.get("locator") or "")[:60]
        score = c.get("score")
        bits.append(f"{loc}({score})" if score is not None else loc)
    out["candidates_summary"] = "; ".join(bits)
    return out
