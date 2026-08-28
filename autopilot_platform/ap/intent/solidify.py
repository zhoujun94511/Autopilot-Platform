"""把已固化 Binding 的 Intent 步降级为确定性关键字步骤（roadmap D2）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# noinspection PyUnresolvedReferences
import yaml

from .bindings import confirm_step_binding, list_stable_bindings, load_binding


def _find_tc_paths(project_dir: str | Path, logical_case_id: str) -> list[Path]:
    root = Path(project_dir)
    lid = (logical_case_id or "").strip()
    if not lid or not root.is_dir():
        return []
    hits: list[Path] = []
    for path in root.rglob("*.tc.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and str(data.get("logical_case_id") or "").strip() == lid:
            hits.append(path)
    return hits


def _stringify_params(params: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (params or {}).items():
        if v is None:
            continue
        out[str(k)] = v if isinstance(v, str) else str(v)
    return out


def solidify_intent_step(
    project_dir: str | Path,
    logical_case_id: str,
    intent_id: str,
    *,
    confirm_binding: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """将 ``intent_act`` 步替换为 Binding 中的 ``keyword_id`` + ``params``。

    - 保留原 comment；remark 追加 ``solidified:intent:{id}``
    - 仅当 Binding 已有 keyword_id 时成功
    - 返回 {ok, path, keyword_id, changed, message}
    """
    root = Path(project_dir)
    lid = (logical_case_id or "").strip()
    iid = (intent_id or "").strip() or "s1"
    if not lid:
        return {"ok": False, "message": "logical_case_id 为空"}

    doc = load_binding(root, lid)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    entry = steps.get(iid) if isinstance(steps.get(iid), dict) else None
    if not entry or not str(entry.get("keyword_id") or "").strip():
        return {
            "ok": False,
            "message": f"Binding 无可用 keyword_id: case={lid} intent={iid}",
        }
    kid = str(entry["keyword_id"]).strip()
    params = _stringify_params(entry.get("params") if isinstance(entry.get("params"), dict) else {})

    paths = _find_tc_paths(root, lid)
    if not paths:
        return {"ok": False, "message": f"未找到 logical_case_id={lid} 的 .tc.yaml"}

    changed_paths: list[str] = []
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError) as exc:
            return {"ok": False, "message": f"读取失败 {path}: {exc}"}
        if not isinstance(data, dict):
            continue
        shells = data.get("shells") if isinstance(data.get("shells"), dict) else {}
        case_steps = shells.get("case") if isinstance(shells.get("case"), list) else []
        touched = False
        for node in case_steps:
            if not isinstance(node, dict):
                continue
            step_id = str(node.get("step") or node.get("keyword") or "").strip()
            p = node.get("params") if isinstance(node.get("params"), dict) else {}
            node_iid = str(p.get("intent_id") or "").strip()
            if step_id != "intent_act" or node_iid != iid:
                continue
            remark = str(node.get("remark") or "")
            if "solidified:" not in remark:
                tag = f"solidified:intent:{iid}"
                node["remark"] = f"{remark}|{tag}" if remark else tag
            node["step"] = kid
            node["params"] = params
            # 保留自然语言线索
            if not str(node.get("comment") or "").strip():
                node["comment"] = str(p.get("text") or p.get("target") or iid)
            touched = True
        if not touched:
            continue
        if dry_run:
            changed_paths.append(str(path))
            continue
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        changed_paths.append(str(path))

    if not changed_paths:
        return {
            "ok": False,
            "keyword_id": kid,
            "message": f"用例中未找到 intent_act intent_id={iid}",
        }

    if confirm_binding and not dry_run:
        confirm_step_binding(root, lid, iid)

    return {
        "ok": True,
        "keyword_id": kid,
        "params": params,
        "paths": changed_paths,
        "changed": len(changed_paths),
        "dry_run": dry_run,
        "message": f"已固化 {len(changed_paths)} 个用例文件 → {kid}",
    }


def solidify_stable(
    project_dir: str | Path,
    *,
    min_streak: int = 3,
    dry_run: bool = False,
    confirm_binding: bool = True,
) -> dict[str, Any]:
    """批量固化 success_streak 达到阈值的 Intent 步。"""

    root = Path(project_dir)
    candidates = list_stable_bindings(root, min_streak=min_streak)
    results: list[dict[str, Any]] = []
    ok_n = 0
    for item in candidates:
        out = solidify_intent_step(
            root,
            str(item["logical_case_id"]),
            str(item["intent_id"]),
            confirm_binding=confirm_binding,
            dry_run=dry_run,
        )
        results.append({**item, **out})
        if out.get("ok"):
            ok_n += 1
    return {
        "ok": ok_n > 0 or not candidates,
        "min_streak": int(min_streak or 3),
        "candidates": len(candidates),
        "solidified": ok_n,
        "dry_run": dry_run,
        "results": results,
        "message": f"稳定步 {len(candidates)}，成功固化 {ok_n}",
    }
