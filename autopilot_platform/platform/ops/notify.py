"""任务终态 Webhook + 运维告警推送（尽力投递，失败不回滚业务）。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from typing import Any
from urllib.parse import urljoin

from .alerts import apply_channel_signing, build_alert_payload, dump_payload
from autopilot_platform.core.webhook_security import pin_webhook_url
from ..core.settings import (
    alert_channel,
    alert_secret,
    alert_webhook_url,
    webhook_secret,
    webhook_url,
)

logger = logging.getLogger(__name__)

# 回调 / metrics 尽力投递：收窄 except，避免 PyCharm「过于宽泛」
_BEST_EFFORT_ERRS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    ImportError,
    LookupError,
    PermissionError,
)


def _sign(body: bytes, secret: str) -> str:
    dig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={dig}"


def _post(
    url: str,
    payload: dict[str, Any],
    *,
    secret: str = "",
    kind: str = "webhook",
    use_mc_signature: bool = True,
) -> bool:
    try:
        import httpx
    except ImportError:
        logger.warning("%s skipped: httpx not installed", kind)
        return False
    body = dump_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "AutoPilot-MC-Webhook/1",
    }
    if use_mc_signature and secret:
        headers["X-MC-Signature"] = _sign(body, secret)
    try:
        current_url = (url or "").strip()
        if not current_url:
            return False
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            for _ in range(4):
                # 单次 resolve + IP 钉死；httpx 不再对主机名二次 DNS
                pinned = pin_webhook_url(current_url)
                req_headers = dict(headers)
                if pinned.host_header:
                    req_headers["Host"] = pinned.host_header
                extensions: dict[str, Any] = {}
                if pinned.sni_hostname:
                    extensions["sni_hostname"] = pinned.sni_hostname
                r = client.post(
                    pinned.url,
                    content=body,
                    headers=req_headers,
                    extensions=extensions or None,
                )
                if r.status_code not in (301, 302, 303, 307, 308):
                    break
                location = (r.headers.get("location") or "").strip()
                if not location:
                    logger.warning("%s %s returned redirect without location", kind, current_url)
                    return False
                # 相对 Location 相对逻辑 URL（主机名）拼接，勿用 pinned IP 作 base
                current_url = urljoin(current_url, location)
            else:
                logger.warning("%s %s exceeded redirect limit", kind, url)
                return False
            if r.status_code >= 400:
                logger.warning(
                    "%s %s → HTTP %s: %s",
                    kind,
                    current_url,
                    r.status_code,
                    r.text[:200],
                )
                return False
            return True
    except Exception as exc:  # noqa: BLE001 — 通知失败不影响主流程
        logger.warning("%s %s failed: %s", kind, url, exc)
        return False


def _post_async(
    url: str,
    payload: dict[str, Any],
    *,
    secret: str = "",
    kind: str = "webhook",
    use_mc_signature: bool = True,
    on_done=None,
) -> None:
    def _run() -> None:
        ok = _post(
            url,
            payload,
            secret=secret,
            kind=kind,
            use_mc_signature=use_mc_signature,
        )
        if on_done is not None:
            try:
                on_done(ok)
            except _BEST_EFFORT_ERRS:
                pass

    threading.Thread(target=_run, daemon=True, name=f"mc-{kind}").start()


def notify_job_event(
    event: str,
    job: dict[str, Any],
    *,
    report: dict[str, Any] | None = None,
    override_url: str = "",
) -> None:
    """异步 POST；URL 优先 override，其次 MC_WEBHOOK_URL。"""
    url = (override_url or webhook_url() or "").strip()
    if not url:
        return
    payload: dict[str, Any] = {"event": event, "job": job}
    if report is not None:
        payload["report"] = report
    _post_async(url, payload, secret=webhook_secret(), kind="webhook")


def notify_design_event(
    event: str,
    *,
    project_id: str,
    case: dict[str, Any],
    override_url: str = "",
) -> None:
    """设计域事件（如 logical_case.approved）→ MC_DESIGN_WEBHOOK_URL。"""
    from ..core.settings import design_webhook_url

    url = (override_url or design_webhook_url() or "").strip()
    if not url:
        return
    payload: dict[str, Any] = {
        "event": event,
        "project_id": project_id,
        "case": case,
    }
    _post_async(url, payload, secret=webhook_secret(), kind="design-webhook")


def send_design_event_sync(
    event: str,
    *,
    project_id: str,
    case: dict[str, Any],
    override_url: str = "",
) -> bool:
    """同步发送设计域 webhook（测试用）。"""
    from ..core.settings import design_webhook_url

    url = (override_url or design_webhook_url() or "").strip()
    if not url:
        return False
    payload: dict[str, Any] = {
        "event": event,
        "project_id": project_id,
        "case": case,
    }
    return _post(url, payload, secret=webhook_secret(), kind="design-webhook")


def _build_alert_request(
    event: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], bool] | None:
    """返回 (url, payload, use_mc_signature)；未配置 URL 则 None。"""
    url = alert_webhook_url()
    if not url:
        return None
    channel = alert_channel()
    url2, feishu_sign = apply_channel_signing(url, channel, alert_secret())
    payload = build_alert_payload(
        channel,
        event,
        summary,
        detail,
        sign_timestamp=feishu_sign.get("timestamp"),
        sign_value=feishu_sign.get("sign"),
    )
    # IM 机器人不吃 X-MC-Signature；仅 json 渠道保留
    use_sig = channel == "json"
    return url2, payload, use_sig


def notify_alert(
    event: str,
    *,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """运维告警：按 MC_ALERT_CHANNEL 格式化后 POST 到 MC_ALERT_WEBHOOK_URL。"""
    built = _build_alert_request(event, summary, detail)
    if built is None:
        return
    url, payload, use_sig = built

    def _done(ok: bool) -> None:
        try:
            from ..core.metrics import note_alert_sent

            note_alert_sent(event, ok=ok)
        except _BEST_EFFORT_ERRS:
            pass

    _post_async(
        url,
        payload,
        secret=alert_secret() if use_sig else "",
        kind="alert",
        use_mc_signature=use_sig,
        on_done=_done,
    )


def send_alert_sync(
    event: str,
    *,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """同步发送（测试接口用）；未配置 URL 返回 False。"""
    built = _build_alert_request(event, summary, detail)
    if built is None:
        return False
    url, payload, use_sig = built
    ok = _post(
        url,
        payload,
        secret=alert_secret() if use_sig else "",
        kind="alert",
        use_mc_signature=use_sig,
    )
    try:
        from ..core.metrics import note_alert_sent

        note_alert_sent(event, ok=ok)
    except _BEST_EFFORT_ERRS:
        pass
    return ok
