"""工程内 step_binding.v1 读写。"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def binding_path(project_dir: str | Path, logical_case_id: str) -> Path:
    root = Path(project_dir)
    bid = (logical_case_id or "").strip() or "_unknown"
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in bid)[:120]
    return root / "bindings" / f"{safe}.json"


def load_binding(project_dir: str | Path, logical_case_id: str) -> dict[str, Any]:
    path = binding_path(project_dir, logical_case_id)
    if not path.is_file():
        return {
            "schema_version": "1.0",
            "logical_case_id": (logical_case_id or "").strip(),
            "revision_id": "",
            "steps": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", "1.0")
    data.setdefault("logical_case_id", (logical_case_id or "").strip())
    data.setdefault("steps", {})
    if not isinstance(data["steps"], dict):
        data["steps"] = {}
    return data


def save_binding(project_dir: str | Path, doc: dict[str, Any]) -> Path:
    lid = str(doc.get("logical_case_id") or "").strip()
    path = binding_path(project_dir, lid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "logical_case_id": lid,
        "revision_id": str(doc.get("revision_id") or ""),
        "steps": doc.get("steps") if isinstance(doc.get("steps"), dict) else {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _snapshot_step(prev: dict[str, Any]) -> dict[str, Any] | None:
    if not prev or not prev.get("keyword_id"):
        return None
    snap: dict[str, Any] = {
        "platform": prev.get("platform"),
        "keyword_id": prev.get("keyword_id"),
        "params": copy.deepcopy(prev.get("params") or {}),
        "candidates": copy.deepcopy(prev.get("candidates") or []),
        "resolver": prev.get("resolver"),
        "heal_count": prev.get("heal_count"),
        "updated_at": prev.get("updated_at"),
    }
    for key in ("channel", "method", "path", "assert", "follow_ups"):
        if key in prev:
            snap[key] = copy.deepcopy(prev.get(key))
    return snap


def upsert_step_binding(
    project_dir: str | Path,
    logical_case_id: str,
    intent_id: str,
    *,
    platform: str,
    keyword_id: str,
    params: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    resolver: str = "heuristic",
    heal_count: int | None = None,
    revision_id: str = "",
    keep_previous: bool = True,
    provisional: bool = False,
    channel: str = "",
    method: str = "",
    path: str = "",
    assert_spec: dict[str, Any] | None = None,
    follow_ups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """写入步 Binding。

    - keep_previous：保留上一版快照到 ``previous``，供误愈回滚
    - provisional：标记为「待下一跑确认」的自愈写回
    - channel/method/path/assert/follow_ups：HTTP 通道扩展（可选）
    """
    doc = load_binding(project_dir, logical_case_id)
    if revision_id:
        doc["revision_id"] = revision_id
    steps = doc.setdefault("steps", {})
    prev = steps.get(intent_id) if isinstance(steps.get(intent_id), dict) else {}
    entry: dict[str, Any] = {
        "platform": platform,
        "keyword_id": keyword_id,
        "params": dict(params or {}),
        "candidates": list(candidates if candidates is not None else prev.get("candidates") or []),
        "resolver": resolver,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "heal_count": int(
            heal_count if heal_count is not None else prev.get("heal_count") or 0
        ),
        # 自愈写回时清零连续成功；否则保留（由 note_step_run 累加）
        "success_streak": (
            0
            if provisional
            else int(prev.get("success_streak") or 0)
        ),
    }
    ch = (channel or str(prev.get("channel") or "")).strip().lower()
    if ch in ("ui", "http", "auto"):
        entry["channel"] = ch
    meth = (method or str(prev.get("method") or "")).strip().upper()
    if meth:
        entry["method"] = meth
    pth = (path or str(prev.get("path") or "")).strip()
    if pth:
        entry["path"] = pth
    a_spec = assert_spec if assert_spec is not None else prev.get("assert")
    if isinstance(a_spec, dict) and a_spec:
        entry["assert"] = dict(a_spec)
    fups = follow_ups if follow_ups is not None else prev.get("follow_ups")
    if isinstance(fups, list) and fups:
        entry["follow_ups"] = list(fups)
    if provisional:
        entry["provisional"] = True
    if keep_previous:
        snap = _snapshot_step(prev) if prev else None
        if snap:
            entry["previous"] = snap
        elif isinstance(prev.get("previous"), dict):
            entry["previous"] = prev["previous"]
    steps[intent_id] = entry
    save_binding(project_dir, doc)
    return entry


def confirm_step_binding(
    project_dir: str | Path,
    logical_case_id: str,
    intent_id: str,
) -> dict[str, Any] | None:
    """缓存命中成功：清除 provisional，固化当前 Binding。"""
    doc = load_binding(project_dir, logical_case_id)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    cur = steps.get(intent_id)
    if not isinstance(cur, dict):
        return None
    if not cur.get("provisional"):
        return cur
    cur = dict(cur)
    cur.pop("provisional", None)
    cur["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    steps[intent_id] = cur
    doc["steps"] = steps
    save_binding(project_dir, doc)
    return cur


def note_step_run(
    project_dir: str | Path,
    logical_case_id: str,
    intent_id: str,
    *,
    success: bool,
    healed: bool = False,
) -> int:
    """更新 Binding.success_streak：成功且未 heal 则 +1，否则清零。返回最新 streak。"""
    lid = (logical_case_id or "").strip()
    iid = (intent_id or "").strip()
    if not lid or not iid:
        return 0
    doc = load_binding(project_dir, lid)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    cur = steps.get(iid)
    if not isinstance(cur, dict):
        return 0
    cur = dict(cur)
    if success and not healed:
        streak = int(cur.get("success_streak") or 0) + 1
    else:
        streak = 0
    cur["success_streak"] = streak
    cur["updated_at"] = datetime.now(timezone.utc).isoformat()
    steps[iid] = cur
    doc["steps"] = steps
    save_binding(project_dir, doc)
    return streak


def list_stable_bindings(
    project_dir: str | Path,
    *,
    min_streak: int = 3,
) -> list[dict[str, Any]]:
    """扫描工程 bindings，返回 success_streak>=min_streak 且有 keyword_id 的步。"""
    root = Path(project_dir)
    bind_dir = root / "bindings"
    if not bind_dir.is_dir():
        return []
    min_n = max(1, int(min_streak or 3))
    out: list[dict[str, Any]] = []
    for path in sorted(bind_dir.glob("*.json")):
        try:
            doc = load_binding(root, path.stem)
        except (OSError, TypeError, ValueError):
            continue
        lid = str(doc.get("logical_case_id") or path.stem).strip()
        steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
        for iid, entry in steps.items():
            if not isinstance(entry, dict):
                continue
            kid = str(entry.get("keyword_id") or "").strip()
            streak = int(entry.get("success_streak") or 0)
            if not kid or streak < min_n:
                continue
            if entry.get("provisional"):
                continue
            out.append(
                {
                    "logical_case_id": lid,
                    "intent_id": str(iid),
                    "keyword_id": kid,
                    "success_streak": streak,
                }
            )
    return out


def rollback_step_binding(
    project_dir: str | Path,
    logical_case_id: str,
    intent_id: str,
    *,
    reason: str = "",
) -> dict[str, Any] | None:
    """误愈回滚：若存在 previous，恢复并标记 rolled_back。"""
    doc = load_binding(project_dir, logical_case_id)
    steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
    cur = steps.get(intent_id)
    if not isinstance(cur, dict):
        return None
    prev = cur.get("previous")
    if not isinstance(prev, dict) or not prev.get("keyword_id"):
        return None
    restored = {
        "platform": prev.get("platform") or cur.get("platform") or "",
        "keyword_id": prev["keyword_id"],
        "params": copy.deepcopy(prev.get("params") or {}),
        "candidates": copy.deepcopy(prev.get("candidates") or []),
        "resolver": prev.get("resolver") or "heuristic",
        "heal_count": int(prev.get("heal_count") or 0),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "rollback_reason": (reason or "")[:240],
        "previous": _snapshot_step(cur),
    }
    for key in ("channel", "method", "path", "assert", "follow_ups"):
        if key in prev:
            restored[key] = copy.deepcopy(prev.get(key))
        elif key in cur and key == "channel":
            restored[key] = cur.get(key)
    steps[intent_id] = restored
    doc["steps"] = steps
    save_binding(project_dir, doc)
    return restored


def ensure_empty_binding(
    project_dir: str | Path,
    logical_case_id: str,
    *,
    revision_id: str = "",
) -> Path:
    doc = load_binding(project_dir, logical_case_id)
    if revision_id:
        doc["revision_id"] = revision_id
    return save_binding(project_dir, doc)
