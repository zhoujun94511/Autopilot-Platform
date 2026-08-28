"""Webhook URL 安全校验，阻止服务端访问内网与云元数据端点。

含 DNS rebinding / TOCTOU 防护：校验解析后把连接钉到已验证 IP，
避免 httpx 再次解析主机名时落到私网（AUD-P1-003）。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


def webhook_allow_loopback() -> bool:
    """本机联调：允许向 127.0.0.1/localhost 推送（默认关，防 SSRF）。

    优先级：运维 runtime JSON > 环境变量 > 默认关（与 cfg_bool 一致）。
    """
    try:
        from autopilot_platform.platform.ops.runtime_config import cfg_bool

        return bool(cfg_bool("MC_WEBHOOK_ALLOW_LOOPBACK", "0"))
    except ImportError:
        raw = (os.environ.get("MC_WEBHOOK_ALLOW_LOOPBACK") or "").strip().lower()
        return raw in ("1", "true", "yes", "on")


def _assert_ip_allowed(address: str, *, allow_loop: bool) -> None:
    ip = ipaddress.ip_address(address)
    if allow_loop and ip.is_loopback:
        return
    if not ip.is_global:
        raise ValueError("webhook_url 不允许私网、回环、链路本地或保留地址")


def resolve_webhook_ips(host: str, port: int | None) -> list[str]:
    """解析主机全部 A/AAAA；任一带私网等非全局地址则拒绝。"""
    host = (host or "").rstrip(".").lower()
    if not host:
        raise ValueError("webhook_url 主机无效或包含凭据")
    allow_loop = webhook_allow_loopback()
    addresses: list[str] = []
    try:
        addresses.append(str(ipaddress.ip_address(host)))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("webhook_url 主机无法解析") from exc
        seen: set[str] = set()
        for item in infos:
            ip_s = str(item[4][0])
            if ip_s not in seen:
                seen.add(ip_s)
                addresses.append(ip_s)
        if not addresses:
            raise ValueError("webhook_url 主机无法解析")
    for address in addresses:
        _assert_ip_allowed(address, allow_loop=allow_loop)
    return addresses


def _format_netloc(host: str, port: int | None) -> str:
    """构造 netloc；IPv6 字面量加方括号。"""
    try:
        ip = ipaddress.ip_address(host)
        host_part = f"[{host}]" if isinstance(ip, ipaddress.IPv6Address) else host
    except ValueError:
        host_part = host
    if port is None:
        return host_part
    return f"{host_part}:{port}"


def _host_header(hostname: str, port: int | None, scheme: str) -> str:
    default = 443 if scheme == "https" else 80
    if port is not None and port != default:
        try:
            ip = ipaddress.ip_address(hostname)
            if isinstance(ip, ipaddress.IPv6Address):
                return f"[{hostname}]:{port}"
        except ValueError:
            pass
        return f"{hostname}:{port}"
    try:
        ip = ipaddress.ip_address(hostname)
        if isinstance(ip, ipaddress.IPv6Address):
            return f"[{hostname}]"
    except ValueError:
        pass
    return hostname


@dataclass(frozen=True)
class PinnedWebhookTarget:
    """已校验并钉死到具体 IP 的 webhook 目标（供 httpx 直连，不再二次 DNS）。"""

    url: str
    host_header: str | None = None
    sni_hostname: str | None = None


def validate_webhook_url(url: str, *, resolve: bool = True) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("webhook_url 仅允许 http/https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("webhook_url 主机无效或包含凭据")

    host = parsed.hostname.rstrip(".").lower()
    allow_loop = webhook_allow_loopback()
    if host == "localhost" or host.endswith(".localhost"):
        if allow_loop:
            return raw
        raise ValueError("webhook_url 不允许本机地址")

    if resolve:
        resolve_webhook_ips(host, parsed.port)
        return raw

    # 创建期：只拦 IP 字面量；域名延后到投递 pin 时解析
    try:
        literal = str(ipaddress.ip_address(host))
    except ValueError:
        return raw
    _assert_ip_allowed(literal, allow_loop=allow_loop)
    return raw


def pin_webhook_url(url: str) -> PinnedWebhookTarget:
    """校验 URL，并把主机名钉到已验证 IP；HTTPS 保留原主机作 SNI。

    只解析一次 DNS，连接 URL 使用字面量 IP，关闭 httpx 二次解析 TOCTOU。
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("webhook_url 为空")
    # 结构校验（localhost / scheme）；DNS 下面只解析一次
    validate_webhook_url(raw, resolve=False)
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").rstrip(".").lower()
    scheme = parsed.scheme.lower()
    port = parsed.port
    allow_loop = webhook_allow_loopback()
    if host == "localhost" or host.endswith(".localhost"):
        if not allow_loop:
            raise ValueError("webhook_url 不允许本机地址")
        return PinnedWebhookTarget(url=raw)

    ips = resolve_webhook_ips(host, port)
    try:
        ipaddress.ip_address(host)
        return PinnedWebhookTarget(url=raw)
    except ValueError:
        pass
    pinned_ip = ips[0]
    netloc = _format_netloc(pinned_ip, port)
    pinned = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return PinnedWebhookTarget(
        url=pinned,
        host_header=_host_header(host, port, scheme),
        sni_hostname=host if scheme == "https" else None,
    )
