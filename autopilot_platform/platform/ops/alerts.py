"""运维告警渠道：通用 JSON / 钉钉 / 飞书 / Slack 载荷与加签。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def format_alert_text(event: str, summary: str, detail: dict[str, Any] | None = None) -> str:
    lines = [f"[AutoPilot 管理台] {event}", summary.strip() or "(no summary)"]
    detail = detail or {}
    job = detail.get("job") if isinstance(detail.get("job"), dict) else None
    if job:
        jid = str(job.get("id") or "")[:12]
        name = str(job.get("name") or "")
        err = str(job.get("error") or "")[:200]
        lines.append(f"job={jid} name={name}")
        if err:
            lines.append(f"error={err}")
    ids = detail.get("job_ids")
    if isinstance(ids, list) and ids:
        lines.append(f"job_ids={','.join(str(x)[:8] for x in ids[:8])}")
        if len(ids) > 8:
            lines.append(f"... +{len(ids) - 8} more")
    return "\n".join(lines)


def build_alert_payload(
    channel: str,
    event: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    *,
    sign_timestamp: str | None = None,
    sign_value: str | None = None,
) -> dict[str, Any]:
    """按渠道组装 POST JSON body。"""
    ch = (channel or "json").strip().lower()
    text = format_alert_text(event, summary, detail)
    if ch == "dingtalk":
        title = f"AutoPilot 管理台 · {event}"
        md = f"### {title}\n\n{text}"
        return {
            "msgtype": "markdown",
            "markdown": {"title": title[:64], "text": md},
        }
    if ch == "feishu":
        body: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if sign_timestamp and sign_value:
            body["timestamp"] = sign_timestamp
            body["sign"] = sign_value
        return body
    if ch == "slack":
        return {"text": text}
    # 默认通用 JSON（自定义接收端 / 兼容十六期）
    return {
        "event": event,
        "summary": summary,
        "detail": detail or {},
        "text": text,
    }


def apply_channel_signing(url: str, channel: str, secret: str) -> tuple[str, dict[str, str]]:
    """返回 (最终 URL, 飞书等放入 body 的 sign 字段)。

    - 钉钉：timestamp/sign 挂到 URL query
    - 飞书：timestamp/sign 放入 body（由调用方合并）
    - 其它：原样
    """
    secret = (secret or "").strip()
    ch = (channel or "json").strip().lower()
    if not secret or ch not in ("dingtalk", "feishu"):
        return url, {}

    if ch == "dingtalk":
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        dig = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sign = base64.b64encode(dig).decode("utf-8")
        return _append_query(url, {"timestamp": ts, "sign": sign}), {}

    # feishu / lark custom bot
    ts = str(round(time.time()))
    string_to_sign = f"{ts}\n{secret}"
    dig = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = base64.b64encode(dig).decode("utf-8")
    return url, {"timestamp": ts, "sign": sign}


def _append_query(url: str, extra: dict[str, str]) -> str:
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q.update(extra)
    # 用 str 六元组，避免 ParseResult._replace 在 stubs 里落到 Literal[b""]
    return urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q), parts.fragment)
    )


def dump_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
