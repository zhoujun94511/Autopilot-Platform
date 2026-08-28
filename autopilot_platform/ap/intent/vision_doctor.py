"""Vision 连通性体检（O10）：不依赖设备会话，检查开关 / Key / 模型 / 可选 ping。"""

from __future__ import annotations

import json
from typing import Any

from .config import (
    intent_vision_enabled,
    vision_accepts_images,
    vision_api_key,
    vision_api_key_configured,
    vision_base_url,
    vision_dom_enabled,
    vision_local_key_allowed,
    vision_model,
    vision_provider_is_text_only,
    vision_screenshot_enabled,
    vision_timeout_sec,
    vision_when,
)
from .provider_profile import detect_provider


def run_vision_doctor(*, ping: bool = False) -> dict[str, Any]:
    """返回结构化体检结果；``ok`` 表示配置足以发起 Vision 调用。"""
    enabled = intent_vision_enabled()
    key = vision_api_key()
    key_present = vision_api_key_configured()
    local_ok = vision_local_key_allowed()
    base = vision_base_url().rstrip("/")
    model = vision_model()
    provider = detect_provider("", model, base)
    text_only = vision_provider_is_text_only(base_url=base, model=model)
    accepts_images = vision_accepts_images(base_url=base, model=model)

    if key:
        key_detail = "已配置"
    elif key_present and not local_ok:
        key_detail = (
            "本机存在 Key，但企业已锁定 Platform URL，默认禁用本机 Vision Key"
            "（与「企业 Key 只在 Platform」对齐）。Runner 注入 Key 时请设 "
            "AUTOPILOT_VISION_ALLOW_LOCAL_KEY=1；用户 IDE 建议保持 "
            "AUTOPILOT_INTENT_VISION=0"
        )
    else:
        key_detail = "缺失（AUTOPILOT_VISION_API_KEY / AP_AI_API_KEY / 厂商 Key）"

    checks: list[dict[str, Any]] = [
        {
            "id": "enabled",
            "ok": enabled,
            "detail": f"AUTOPILOT_INTENT_VISION={'1' if enabled else '0'}",
        },
        {
            "id": "local_key_policy",
            "ok": local_ok or not key_present,
            "detail": (
                "允许本机 Vision Key"
                if local_ok
                else "企业锁定 URL：默认禁止本机 Vision Key"
            ),
        },
        {
            "id": "api_key",
            "ok": bool(key),
            "detail": key_detail,
        },
        {
            "id": "base_url",
            "ok": bool(base),
            "detail": base or "(empty)",
        },
        {
            "id": "model",
            "ok": bool(model),
            "detail": model or "(empty)",
        },
        {
            "id": "when",
            "ok": True,
            "detail": vision_when(),
        },
        {
            "id": "provider",
            "ok": True,
            "detail": (
                f"{provider}; text_only={text_only}; accepts_images={accepts_images}; "
                f"screenshot={vision_screenshot_enabled()}; dom={vision_dom_enabled()}"
            ),
        },
    ]

    ping_result: dict[str, Any] | None = None
    if ping:
        if not (enabled and key and base and model):
            ping_result = {
                "ok": False,
                "detail": "跳过 ping：开关/Key/base_url/model 未就绪",
            }
        else:
            ping_result = _ping_chat(base_url=base, api_key=key, model=model)
        checks.append(
            {
                "id": "ping",
                "ok": bool(ping_result and ping_result.get("ok")),
                "detail": str((ping_result or {}).get("detail") or ""),
            }
        )

    config_ok = enabled and bool(key) and bool(base) and bool(model)
    ok = config_ok and (ping_result.get("ok") if ping and ping_result else True)
    return {
        "ok": bool(ok),
        "config_ok": bool(config_ok),
        "enabled": enabled,
        "provider": provider,
        "model": model,
        "base_url": base,
        "text_only": text_only,
        "accepts_images": accepts_images,
        "checks": checks,
        "ping": ping_result,
    }


def _ping_chat(*, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    try:
        import httpx
    except ImportError:
        return {"ok": False, "detail": "httpx 未安装"}

    url = f"{base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Reply with exactly: ok"},
        ],
        "max_tokens": 8,
    }
    try:
        with httpx.Client(timeout=min(20.0, float(vision_timeout_sec() or 20))) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "detail": f"HTTP {resp.status_code}: {(resp.text or '')[:240]}",
            }
        data = resp.json()
        try:
            content = str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            content = json.dumps(data, ensure_ascii=False)[:120]
        return {"ok": True, "detail": f"HTTP {resp.status_code}; content={content[:80]!r}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:240]}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:240]}


def format_doctor_report(report: dict[str, Any]) -> str:
    lines = [
        f"vision-doctor: {'OK' if report.get('ok') else 'FAIL'}",
        f"  enabled={report.get('enabled')} provider={report.get('provider')} "
        f"model={report.get('model')}",
        f"  base_url={report.get('base_url')}",
        f"  text_only={report.get('text_only')} accepts_images={report.get('accepts_images')}",
    ]
    for c in report.get("checks") or []:
        if not isinstance(c, dict):
            continue
        mark = "OK" if c.get("ok") else "FAIL"
        lines.append(f"  [{mark}] {c.get('id')}: {c.get('detail')}")
    return "\n".join(lines)
