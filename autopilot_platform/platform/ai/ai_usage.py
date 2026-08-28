"""LLM / Vision token 用量解析、落盘与软预算。

不替代厂商账单；目标：可观测 + 可选日限额告警/阻断。

归一字段（OpenAI / DeepSeek / Anthropic / Gemini 兼容）：
  prompt_tokens / completion_tokens / total_tokens
  cached_tokens      — 缓存命中（读缓存）
  cache_miss_tokens  — 未命中（DeepSeek 等）
  cache_write_tokens — 写入缓存（Anthropic cache creation 等）
"""

from __future__ import annotations

import json
import logging
import os
import threading

# contextvars 是 3.7+ 标准库，同名 PyPI backport 会让依赖检查误报
# noinspection PyPackageRequirements
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("autopilot_platform.platform.ai.usage")

_lock = threading.Lock()
# 进程内当日累计（重启后从 JSONL 懒加载）
_day_key: str = ""
_ZERO = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cached_tokens": 0,
    "cache_miss_tokens": 0,
    "cache_write_tokens": 0,
    "calls": 0,
}
_day_totals: dict[str, int] = dict(_ZERO)
_day_by_project: dict[str, dict[str, int]] = {}
_day_by_org: dict[str, dict[str, int]] = {}
_loaded_from_disk = False

_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_miss_tokens",
    "cache_write_tokens",
)

# 请求作用域：设计 Chat / 生成可 set，供 check/record 自动带上分账字段
_ai_scope: ContextVar[dict[str, str]] = ContextVar(
    "ap_ai_billing_scope", default={}
)


def _as_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def empty_usage() -> dict[str, int]:
    return {k: 0 for k in _USAGE_KEYS}


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    """规范化一次调用用量；补全 total。"""
    u = empty_usage()
    if not isinstance(usage, dict):
        return u
    for key in _USAGE_KEYS:
        u[key] = _as_non_negative_int(usage.get(key))
    if u["total_tokens"] <= 0 and (u["prompt_tokens"] or u["completion_tokens"]):
        u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
    return u


def extract_usage(payload: Any) -> dict[str, int]:
    """从厂商响应取出用量；缺省字段为 0。"""
    if not isinstance(payload, dict):
        return empty_usage()

    raw = payload.get("usage")
    if isinstance(raw, dict):
        return _extract_from_usage_object(raw)

    # Gemini generateContent 等
    meta = payload.get("usageMetadata") or payload.get("usage_metadata")
    if isinstance(meta, dict):
        prompt = _as_non_negative_int(
            meta.get("promptTokenCount") or meta.get("prompt_token_count")
        )
        completion = _as_non_negative_int(
            meta.get("candidatesTokenCount")
            or meta.get("candidates_token_count")
            or meta.get("completionTokenCount")
        )
        total = _as_non_negative_int(
            meta.get("totalTokenCount") or meta.get("total_token_count")
        )
        cached = _as_non_negative_int(
            meta.get("cachedContentTokenCount")
            or meta.get("cached_content_token_count")
        )
        u = empty_usage()
        u["prompt_tokens"] = prompt
        u["completion_tokens"] = completion
        u["total_tokens"] = total
        u["cached_tokens"] = cached
        if u["total_tokens"] <= 0 and (prompt or completion):
            u["total_tokens"] = prompt + completion
        return u

    return empty_usage()


def _extract_from_usage_object(raw: dict[str, Any]) -> dict[str, int]:
    # OpenAI 兼容 + Anthropic 别名
    prompt = _as_non_negative_int(raw.get("prompt_tokens") or raw.get("input_tokens"))
    completion = _as_non_negative_int(
        raw.get("completion_tokens") or raw.get("output_tokens")
    )
    total = _as_non_negative_int(raw.get("total_tokens"))

    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = _as_non_negative_int(details.get("cached_tokens"))

    # DeepSeek：prompt_cache_hit_tokens / prompt_cache_miss_tokens
    if raw.get("prompt_cache_hit_tokens") is not None:
        cached = max(cached, _as_non_negative_int(raw.get("prompt_cache_hit_tokens")))
    cache_miss = _as_non_negative_int(raw.get("prompt_cache_miss_tokens"))

    # Anthropic：cache_read_input_tokens / cache_creation_input_tokens
    if raw.get("cache_read_input_tokens") is not None:
        cached = max(cached, _as_non_negative_int(raw.get("cache_read_input_tokens")))
    cache_write = _as_non_negative_int(raw.get("cache_creation_input_tokens"))

    # 少数网关顶层 cached_tokens
    if not cached:
        cached = _as_non_negative_int(raw.get("cached_tokens"))
    if not cache_write:
        cache_write = _as_non_negative_int(raw.get("cache_write_tokens"))
    if not cache_miss:
        cache_miss = _as_non_negative_int(raw.get("cache_miss_tokens"))

    if total <= 0 and (prompt or completion):
        total = prompt + completion

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "cache_miss_tokens": cache_miss,
        "cache_write_tokens": cache_write,
    }


def _today() -> str:
    return date.today().isoformat()


def _usage_dir() -> Path:
    try:
        from ..core.settings import artifacts_root

        # 与制品同级的 data 根：artifacts 的 parent
        root = artifacts_root().parent / "ai_usage"
    except (ImportError, AttributeError, OSError, TypeError, RuntimeError):
        root = Path(os.environ.get("MC_AI_USAGE_DIR") or ".autopilot_ai_usage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _jsonl_path(day: str | None = None) -> Path:
    return _usage_dir() / f"usage-{(day or _today())}.jsonl"


def daily_token_budget() -> int:
    """全局日累计 total_tokens 软/硬预算；0=关闭。"""
    raw = _runtime_cfg("AP_AI_DAILY_TOKEN_BUDGET", "0")
    try:
        return max(0, int(raw or "0"))
    except ValueError:
        return 0


def project_daily_token_budget() -> int:
    """按 project_id 分账的日预算；0=关闭。"""
    raw = _runtime_cfg("AP_AI_PROJECT_DAILY_TOKEN_BUDGET", "0")
    try:
        return max(0, int(raw or "0"))
    except ValueError:
        return 0


def org_daily_token_budget() -> int:
    """按 org_id 分账的日预算；0=关闭。"""
    raw = _runtime_cfg("AP_AI_ORG_DAILY_TOKEN_BUDGET", "0")
    try:
        return max(0, int(raw or "0"))
    except ValueError:
        return 0


def enforce_token_budget() -> bool:
    """为真时超预算抛错；否则仅 warning。"""
    return _runtime_cfg("AP_AI_ENFORCE_TOKEN_BUDGET", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _runtime_cfg(key: str, default: str = "") -> str:
    """预算也必须读取平台运行时配置中心，不能只认启动进程环境变量。"""
    try:
        from ..ops.runtime_config import cfg_str

        return cfg_str(key, default).strip()
    except (ImportError, OSError, KeyError, TypeError, ValueError, AttributeError):
        return (os.environ.get(key) or default).strip()


def set_ai_billing_scope(
    *,
    project_id: str = "",
    org_id: str = "",
) -> Any:
    """设置当前协程/请求的计费作用域；返回 token 供 reset。"""
    scope = {
        "project_id": (project_id or "").strip(),
        "org_id": (org_id or "").strip(),
    }
    return _ai_scope.set(scope)


def reset_ai_billing_scope(token: Any) -> None:
    try:
        _ai_scope.reset(token)
    except (ValueError, LookupError):
        pass


def get_ai_billing_scope() -> dict[str, str]:
    raw = _ai_scope.get()
    if not isinstance(raw, dict):
        return {"project_id": "", "org_id": ""}
    return {
        "project_id": str(raw.get("project_id") or "").strip(),
        "org_id": str(raw.get("org_id") or "").strip(),
    }


def _row_usage(row: dict[str, Any]) -> dict[str, int]:
    raw = row.get("usage") if isinstance(row.get("usage"), dict) else row
    return normalize_usage(raw if isinstance(raw, dict) else None)


def _add_into(bucket: dict[str, dict[str, int]], key: str, u: dict[str, int]) -> None:
    kid = (key or "").strip()
    if not kid:
        return
    slot = bucket.setdefault(kid, dict(_ZERO))
    for k in _USAGE_KEYS:
        slot[k] += u[k]
    slot["calls"] += 1


def _ensure_day_loaded() -> None:
    global _day_key, _day_totals, _day_by_project, _day_by_org, _loaded_from_disk
    today = _today()
    if _day_key == today and _loaded_from_disk:
        return
    totals = dict(_ZERO)
    by_project: dict[str, dict[str, int]] = {}
    by_org: dict[str, dict[str, int]] = {}
    path = _jsonl_path(today)
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                u = _row_usage(row)
                for key in _USAGE_KEYS:
                    totals[key] += u[key]
                totals["calls"] += 1
                _add_into(by_project, str(row.get("project_id") or ""), u)
                _add_into(by_org, str(row.get("org_id") or ""), u)
        except OSError as exc:
            log.debug("load usage jsonl failed: %s", exc)
    _day_key = today
    _day_totals = totals
    _day_by_project = by_project
    _day_by_org = by_org
    _loaded_from_disk = True


def reset_for_tests() -> None:
    global _day_key, _day_totals, _day_by_project, _day_by_org, _loaded_from_disk
    with _lock:
        _day_key = ""
        _day_totals = dict(_ZERO)
        _day_by_project = {}
        _day_by_org = {}
        _loaded_from_disk = False
    try:
        _ai_scope.set({})
    except LookupError:
        pass


def budget_config_warnings() -> list[str]:
    """AI 预算配置体检：未配预算或只告警不拦截时给出可见提示。"""
    warns: list[str] = []
    global_budget = daily_token_budget()
    project_budget = project_daily_token_budget()
    org_budget = org_daily_token_budget()
    if global_budget <= 0 and project_budget <= 0 and org_budget <= 0:
        warns.append(
            "未配置任何 AI 日 token 预算（AP_AI_DAILY_TOKEN_BUDGET / "
            "AP_AI_PROJECT_DAILY_TOKEN_BUDGET / AP_AI_ORG_DAILY_TOKEN_BUDGET），"
            "异常调用可无上限消耗厂商额度。"
        )
    elif not enforce_token_budget():
        warns.append(
            "已配预算但未开启拦截（AP_AI_ENFORCE_TOKEN_BUDGET=0）：超限只告警不阻断。"
        )
    return warns


def _raise_or_warn(msg: str) -> None:
    if enforce_token_budget():
        raise RuntimeError(msg)
    log.warning("%s", msg)


def check_budget_before_call(
    *,
    project_id: str | None = None,
    org_id: str | None = None,
) -> None:
    """调用前检查日预算（全局 → 项目 → 组织）；enforce 时超限抛 RuntimeError。"""
    scope = get_ai_billing_scope()
    pid = (project_id if project_id is not None else scope.get("project_id") or "").strip()
    oid = (org_id if org_id is not None else scope.get("org_id") or "").strip()

    global_budget = daily_token_budget()
    project_budget = project_daily_token_budget()
    org_budget = org_daily_token_budget()
    if global_budget <= 0 and project_budget <= 0 and org_budget <= 0:
        return

    with _lock:
        _ensure_day_loaded()
        used_global = int(_day_totals.get("total_tokens") or 0)
        used_project = int((_day_by_project.get(pid) or {}).get("total_tokens") or 0) if pid else 0
        used_org = int((_day_by_org.get(oid) or {}).get("total_tokens") or 0) if oid else 0

    if 0 < global_budget <= used_global:
        _raise_or_warn(
            f"AI 日 token 预算已用尽：used={used_global} budget={global_budget}"
            f"（AP_AI_DAILY_TOKEN_BUDGET）"
        )
    if pid and 0 < project_budget <= used_project:
        _raise_or_warn(
            f"AI 项目日 token 预算已用尽：project={pid} used={used_project} "
            f"budget={project_budget}（AP_AI_PROJECT_DAILY_TOKEN_BUDGET）"
        )
    if oid and 0 < org_budget <= used_org:
        _raise_or_warn(
            f"AI 组织日 token 预算已用尽：org={oid} used={used_org} "
            f"budget={org_budget}（AP_AI_ORG_DAILY_TOKEN_BUDGET）"
        )


def record_usage(
    usage: dict[str, int] | None,
    *,
    source: str = "chat",
    model: str = "",
    provider: str = "",
    project_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, int]:
    """记录一次调用用量；返回规范化 usage。"""
    u = normalize_usage(usage)
    scope = get_ai_billing_scope()
    pid = (project_id if project_id is not None else scope.get("project_id") or "").strip()
    oid = (org_id if org_id is not None else scope.get("org_id") or "").strip()

    try:
        from . import ai_config

        provider = provider or ai_config.ai_provider()
        model = model or ai_config.ai_model()
    except (ImportError, AttributeError, TypeError, RuntimeError, ValueError):
        pass

    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": (source or "chat").strip() or "chat",
        "provider": provider or "",
        "model": model or "",
        "project_id": pid,
        "org_id": oid,
        "usage": u,
    }
    with _lock:
        _ensure_day_loaded()
        for key in _USAGE_KEYS:
            _day_totals[key] += u[key]
        _day_totals["calls"] += 1
        _add_into(_day_by_project, pid, u)
        _add_into(_day_by_org, oid, u)
        day_snapshot = dict(_day_totals)
        project_snapshot = dict(_day_by_project.get(pid) or _ZERO) if pid else {}
        org_snapshot = dict(_day_by_org.get(oid) or _ZERO) if oid else {}
        try:
            with _jsonl_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.debug("append usage jsonl failed: %s", exc)

    if u["total_tokens"] or u["prompt_tokens"] or u["completion_tokens"] or u["cached_tokens"]:
        log.info(
            "ai usage source=%s model=%s project=%s org=%s prompt=%s completion=%s "
            "cached=%s miss=%s write=%s total=%s day_total=%s calls=%s",
            event["source"],
            event["model"],
            pid or "-",
            oid or "-",
            u["prompt_tokens"],
            u["completion_tokens"],
            u["cached_tokens"],
            u["cache_miss_tokens"],
            u["cache_write_tokens"],
            u["total_tokens"],
            day_snapshot["total_tokens"],
            day_snapshot["calls"],
        )
    else:
        log.debug("ai usage missing in response source=%s model=%s", event["source"], event["model"])

    global_budget = daily_token_budget()
    if 0 < global_budget <= day_snapshot["total_tokens"]:
        msg = (
            f"AI 日 token 已达预算：day_total={day_snapshot['total_tokens']} "
            f"budget={global_budget}"
        )
        if enforce_token_budget():
            log.error("%s", msg)
        else:
            log.warning("%s", msg)

    project_budget = project_daily_token_budget()
    project_total = int(project_snapshot.get("total_tokens") or 0)
    if pid and 0 < project_budget <= project_total:
        msg = (
            f"AI 项目日 token 已达预算：project={pid} "
            f"total={project_total} budget={project_budget}"
        )
        if enforce_token_budget():
            log.error("%s", msg)
        else:
            log.warning("%s", msg)

    org_budget = org_daily_token_budget()
    org_total = int(org_snapshot.get("total_tokens") or 0)
    if oid and 0 < org_budget <= org_total:
        msg = (
            f"AI 组织日 token 已达预算：org={oid} "
            f"total={org_total} budget={org_budget}"
        )
        if enforce_token_budget():
            log.error("%s", msg)
        else:
            log.warning("%s", msg)
    return u


def usage_summary(*, project_id: str = "", top_projects: int = 8) -> dict[str, Any]:
    """供 design_stats / ops 读取。"""
    pid = (project_id or "").strip()
    with _lock:
        _ensure_day_loaded()
        totals = dict(_day_totals)
        day = _day_key or _today()
        by_project = {k: dict(v) for k, v in _day_by_project.items()}
        by_org = {k: dict(v) for k, v in _day_by_org.items()}
    budget = daily_token_budget()
    p_budget = project_daily_token_budget()
    o_budget = org_daily_token_budget()
    prompt = totals["prompt_tokens"]
    cached = totals["cached_tokens"]
    hit_rate = round(cached / prompt, 4) if prompt > 0 else None
    project_rows = sorted(
        (
            {"project_id": k, "total_tokens": int(v.get("total_tokens") or 0), "calls": int(v.get("calls") or 0)}
            for k, v in by_project.items()
        ),
        key=lambda x: -int(x["total_tokens"]),
    )[: max(0, int(top_projects))]
    project_used = int((by_project.get(pid) or {}).get("total_tokens") or 0) if pid else None
    return {
        "day": day,
        "prompt_tokens": prompt,
        "completion_tokens": totals["completion_tokens"],
        "total_tokens": totals["total_tokens"],
        "cached_tokens": cached,
        "cache_miss_tokens": totals["cache_miss_tokens"],
        "cache_write_tokens": totals["cache_write_tokens"],
        "cache_hit_rate": hit_rate,
        "calls": totals["calls"],
        "daily_budget": budget,
        "budget_remaining": (budget - totals["total_tokens"]) if budget > 0 else None,
        "project_daily_budget": p_budget,
        "org_daily_budget": o_budget,
        "project_id": pid,
        "project_total_tokens": project_used,
        "project_budget_remaining": (
            (p_budget - project_used) if pid and p_budget > 0 and project_used is not None else None
        ),
        "top_projects": project_rows,
        "org_count": len(by_org),
        "enforce": enforce_token_budget(),
        "config_warnings": budget_config_warnings(),
        "note": (
            "进程内+JSONL 日累计（含缓存命中与项目/组织分账）；非厂商账单。"
            "AP_AI_DAILY_TOKEN_BUDGET / AP_AI_PROJECT_DAILY_TOKEN_BUDGET / "
            "AP_AI_ORG_DAILY_TOKEN_BUDGET + AP_AI_ENFORCE_TOKEN_BUDGET。"
        ),
        "jsonl": str(_jsonl_path(day)),
    }
