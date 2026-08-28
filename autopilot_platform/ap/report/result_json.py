"""写出结构化 result.json（与 Platform contracts/result.v1 对齐；HTML 仍为人读产物）。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fail_class import classify_step


def write_result_json(
    path: str,
    *,
    job_id: str,
    status: str,
    suite_name: str,
    passed: int,
    failed: int,
    total: int,
    duration_ms: int,
    summary: str = "",
    artifact_id: str = "",
    app_build_id: str = "",
    project_id: str = "",
    platform: str = "",
    backend_mode: str = "",
    device_udids: list[str] | None = None,
    runner_id: str = "",
    html_report_path: str = "",
    cases: list[dict[str, Any]] | None = None,
    runtime_version: str = "",
) -> str:
    payload = {
        "schema_version": "1.0",
        "job_id": job_id,
        "execution_id": job_id,
        "status": status,
        "artifact_id": artifact_id or None,
        "app_build_id": app_build_id or None,
        "project_id": project_id or None,
        "runtime_version": runtime_version or None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform,
            "backend_mode": backend_mode,
            "device_udids": list(device_udids or []),
            "runner_id": runner_id or None,
        },
        "suite": {
            "name": suite_name,
            "passed": int(passed),
            "failed": int(failed),
            "total": int(total),
            "duration_ms": int(duration_ms),
            "summary": summary,
        },
        "cases": list(cases or []),
        "attachments": _attachments_from_cases(cases or []),
        "html_report_path": html_report_path or None,
    }
    clean = {k: v for k, v in payload.items() if v is not None}
    clean["environment"] = {
        k: v for k, v in payload["environment"].items() if v not in (None, [])
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return os.path.abspath(path)


def _attachments_from_cases(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    """从 step 证据路径汇总到顶层 attachments（D3 失败回放索引）。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        cname = str(case.get("name") or "")
        for step in case.get("steps") or []:
            if not isinstance(step, dict):
                continue
            for kind, key in (
                ("screenshot", "screenshot_path"),
                ("screenshot_before", "screenshot_before_path"),
                ("dom", "dom_path"),
            ):
                path = str(step.get(key) or "").strip()
                if not path or path in seen:
                    continue
                seen.add(path)
                item: dict[str, str] = {"kind": kind, "path": path}
                if cname:
                    item["case"] = cname
                    item["case_name"] = cname  # schema 兼容别名
                iid = str(step.get("intent_id") or "").strip()
                if iid:
                    item["intent_id"] = iid
                out.append(item)
    return out


def _trace_fields_from_path(source_path: str) -> dict[str, str]:
    """从 .tc.yaml 轻量读取 schema 2.0 追踪字段（失败则空）。"""
    path = (source_path or "").strip()
    if not path or not path.lower().endswith((".yaml", ".yml")):
        return {}
    try:
        import yaml  # 延迟：可选 extra，未装则跳过 YAML 追踪字段
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, UnicodeError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("logical_case_id", "automation_case_id", "case_key"):
        val = str(data.get(key) or "").strip()
        if val:
            out[key] = val
    return out


_VERIFY_KW_MARKERS = ("verify", "assert", "check_exist", "check_text")


def _is_verify_keyword(keyword_id: str) -> bool:
    kid = (keyword_id or "").lower()
    return any(m in kid for m in _VERIFY_KW_MARKERS)


def _append_intent_trace_fields(row: dict[str, Any], sr: Any) -> None:
    """把 Intent Trace / 验证状态写入 step row（仅非空/有意义字段）。"""
    strategy = str(getattr(sr, "resolve_strategy", "") or "")
    if strategy:
        row["resolve_strategy"] = strategy
    try:
        cand_n = int(getattr(sr, "candidate_count", 0) or 0)
    except (TypeError, ValueError):
        cand_n = 0
    if cand_n:
        row["candidate_count"] = cand_n
    plat = str(getattr(sr, "perception_platform", "") or "")
    if plat:
        row["perception_platform"] = plat
    try:
        el_n = int(getattr(sr, "perception_element_count", 0) or 0)
    except (TypeError, ValueError):
        el_n = 0
    if el_n:
        row["perception_element_count"] = el_n
    if bool(getattr(sr, "perception_used_screenshot", False)):
        row["perception_used_screenshot"] = True
    try:
        lat = int(getattr(sr, "latency_ms", 0) or 0)
    except (TypeError, ValueError):
        lat = 0
    if lat:
        row["latency_ms"] = lat
    try:
        tokens = int(getattr(sr, "vision_tokens", 0) or 0)
    except (TypeError, ValueError):
        tokens = 0
    if tokens:
        row["vision_tokens"] = tokens
    vs = str(getattr(sr, "verification_status", "") or "")
    if vs:
        row["verification_status"] = vs
    shot = str(getattr(sr, "screenshot_path", "") or "")
    if shot:
        row["screenshot_path"] = shot
    shot_before = str(getattr(sr, "screenshot_before_path", "") or "")
    if shot_before:
        row["screenshot_before_path"] = shot_before
    dom = str(getattr(sr, "dom_path", "") or "")
    if dom:
        row["dom_path"] = dom


def _upgrade_verification_from_following(
    step_rows: list[dict[str, Any]],
    raw_steps: list[Any],
    row_indices: list[int],
) -> None:
    """若后续步骤是断言且 PASS，将前序 Intent 的 missing 升级为 passed。"""
    for row, idx in zip(step_rows, row_indices):
        if str(row.get("verification_status") or "") != "missing":
            continue
        if str(row.get("status") or "") != "PASS":
            continue
        if not (row.get("intent_id") or row.get("binding_hit")):
            continue
        for j in range(idx + 1, len(raw_steps)):
            nxt = raw_steps[j]
            kid = str(getattr(nxt, "keyword_id", "") or "")
            rkw = str(getattr(nxt, "resolved_keyword_id", "") or "")
            if str(getattr(nxt, "intent_id", "") or "").strip():
                # 下一个 Intent：若其本身是断言动作则也可作为验证
                if _is_verify_keyword(kid) or _is_verify_keyword(rkw):
                    if str(getattr(nxt, "status", "") or "") == "PASS":
                        row["verification_status"] = "passed"
                    elif str(getattr(nxt, "status", "") or "") == "FAIL":
                        row["verification_status"] = "failed"
                break
            if not (_is_verify_keyword(kid) or _is_verify_keyword(rkw)):
                continue
            if str(getattr(nxt, "status", "") or "") == "PASS":
                row["verification_status"] = "passed"
            elif str(getattr(nxt, "status", "") or "") == "FAIL":
                row["verification_status"] = "failed"
            break


def _case_relative_path(src: str, root: str) -> str:
    normalized = src.replace("\\", "/")
    if not root:
        return normalized
    try:
        return os.path.relpath(src, root).replace("\\", "/")
    except ValueError:
        return normalized


def _case_item_from_result(rr: Any, *, root: str) -> dict[str, Any]:
    """单条 CaseResult → result.v1 case 对象。"""
    item: dict[str, Any] = {
        "name": str(getattr(rr, "case_name", "") or ""),
        "status": "passed" if bool(getattr(rr, "passed", False)) else "failed",
        "duration_ms": int(getattr(rr, "duration_ms", 0) or 0),
    }
    src = str(getattr(rr, "source_path", "") or "").strip()
    if src:
        item["relative_path"] = _case_relative_path(src, root)
        item.update(_trace_fields_from_path(src))
    # 首个 FAIL 摘要 + intent 步进
    raw_steps = list(getattr(rr, "results", None) or [])
    step_rows: list[dict[str, Any]] = []
    row_indices: list[int] = []
    for idx, sr in enumerate(raw_steps):
        kid = str(getattr(sr, "keyword_id", "") or "")
        row: dict[str, Any] = {
            "name": str(getattr(sr, "comment", "") or kid or ""),
            "keyword_id": kid,
            "status": str(getattr(sr, "status", "") or ""),
        }
        try:
            dur = int(getattr(sr, "duration_ms", 0) or 0)
        except (TypeError, ValueError):
            dur = 0
        if dur:
            row["duration_ms"] = dur
        try:
            http_status = int(getattr(sr, "http_status", 0) or 0)
        except (TypeError, ValueError):
            http_status = 0
        if http_status:
            row["http_status"] = http_status
        http_url = str(getattr(sr, "http_url", "") or "").strip()
        if http_url:
            row["http_url"] = http_url
        try:
            http_elapsed = int(getattr(sr, "http_elapsed_ms", 0) or 0)
        except (TypeError, ValueError):
            http_elapsed = 0
        if http_elapsed:
            row["http_elapsed_ms"] = http_elapsed
        iid = str(getattr(sr, "intent_id", "") or "")
        if iid:
            row["intent_id"] = iid
        hit = str(getattr(sr, "binding_hit", "") or "")
        if hit:
            row["binding_hit"] = hit
        if bool(getattr(sr, "heal_applied", False)):
            row["heal_applied"] = True
        rkw = str(getattr(sr, "resolved_keyword_id", "") or "")
        if rkw:
            row["resolved_keyword_id"] = rkw
        fr = str(getattr(sr, "fail_reason", "") or "")
        if fr:
            row["fail_reason"] = fr
            row["fail_reason_label"] = str(getattr(sr, "fail_reason_label", "") or "")
        if str(getattr(sr, "status", "") or "") == "FAIL":
            cls = classify_step(sr)
            if cls.get("fail_class"):
                row["fail_class"] = cls["fail_class"]
                row["fail_class_label"] = cls.get("fail_class_label") or ""
                if "fail_class" not in item:
                    item["fail_class"] = cls["fail_class"]
                    item["fail_class_label"] = cls.get("fail_class_label") or ""
            if cls.get("attribution"):
                row["attribution"] = cls["attribution"]
                row["attribution_label"] = cls.get("attribution_label") or ""
                if "attribution" not in item:
                    item["attribution"] = cls["attribution"]
                    item["attribution_label"] = cls.get("attribution_label") or ""
        if bool(getattr(sr, "rolled_back", False)):
            row["rolled_back"] = True
        _append_intent_trace_fields(row, sr)
        msg = str(getattr(sr, "message", "") or "")
        if getattr(sr, "status", "") == "FAIL" and msg:
            row["error_message"] = msg[:500]
            if "error_message" not in item:
                item["error_message"] = msg[:500]
        if iid or hit or getattr(sr, "status", "") == "FAIL" or http_url or http_status:
            step_rows.append(row)
            row_indices.append(idx)
    if step_rows:
        _upgrade_verification_from_following(step_rows, raw_steps, row_indices)
        item["steps"] = step_rows
    # 把本地状态决策的证据写进 result.json，供 Platform 使用同一规则回写。
    # Platform 不可访问 Runner 工程文件，不能在服务端重新猜 Binding/mapping。
    logical_case_id = str(item.get("logical_case_id") or "").strip()
    if src and logical_case_id:
        # 延迟：写证据才读 Binding/mapping；勿让 result.json 急切拉 mgmt 包
        from ..mgmt.binding_coverage import status_for_passed_case
        from ..mgmt.case_trace import has_mapping_required

        mapping_required = has_mapping_required(src)
        item["mapping_required"] = mapping_required
        if bool(getattr(rr, "passed", False)):
            evidence = status_for_passed_case(
                tc_path=src,
                logical_case_id=logical_case_id,
                project_dir=root or None,
            )
            # B1：存在未验证 Intent 动作时不晋升 EXECUTABLE
            if evidence in ("EXECUTABLE", "BINDING_PARTIAL") and _has_missing_verification(
                step_rows
            ):
                evidence = "PENDING_VERIFY"
            item["automation_status_evidence"] = evidence
        else:
            item["automation_status_evidence"] = (
                "MAPPING_REQUIRED" if mapping_required else "DEBUGGING"
            )
    if item.get("status") == "failed":
        from .fail_review import review_failed_case  # 延迟：仅失败用例事后二审

        review = review_failed_case(item)
        if review:
            item["qa_review"] = review
            roots = review.get("root_causes") or []
            if roots:
                item["root_causes"] = roots
    return item


def cases_from_suite(suite: Any, *, project_dir: str = "") -> list[dict[str, Any]]:
    """SuiteResult → result.v1 cases[]。"""
    root = os.path.abspath(project_dir) if project_dir else ""
    return [
        _case_item_from_result(rr, root=root)
        for rr in (getattr(suite, "results", None) or [])
    ]


def _has_missing_verification(step_rows: list[dict[str, Any]]) -> bool:
    for row in step_rows or []:
        if not isinstance(row, dict):
            continue
        if not (row.get("intent_id") or row.get("binding_hit")):
            continue
        if str(row.get("status") or "") != "PASS":
            continue
        if str(row.get("verification_status") or "") == "missing":
            return True
    return False


def default_result_json_path(project_dir: str, html_path: str = "") -> str:
    """与 HTML 同目录写 result.json；否则写到 reports/result_latest.json。"""
    if html_path:
        return os.path.join(os.path.dirname(os.path.abspath(html_path)), "result.json")
    reports = os.path.join(os.path.abspath(project_dir), "reports")
    os.makedirs(reports, exist_ok=True)
    return os.path.join(reports, "result_latest.json")
