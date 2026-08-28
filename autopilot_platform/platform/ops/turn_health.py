"""TURN/STUN 最小健康探针（RFC 5389 Binding request）。"""

from __future__ import annotations

import os
import socket
import struct
from urllib.parse import urlsplit

from ..core.settings import turn_enabled, turn_urls

_MAGIC_COOKIE = 0x2112A442


def _host_port(url: str) -> tuple[str, int]:
    normalized = url.replace("stuns:", "udp://", 1).replace("stun:", "udp://", 1)
    normalized = normalized.replace("turns:", "tcp://", 1).replace("turn:", "udp://", 1)
    parts = urlsplit(normalized)
    if not parts.hostname:
        raise ValueError("TURN URL 缺少主机名")
    default_port = 5349 if url.startswith(("turns:", "stuns:")) else 3478
    return parts.hostname, int(parts.port or default_port)


def check_turn_health(timeout: float = 2.0) -> dict[str, object]:
    if not turn_enabled():
        return {"enabled": False, "status": "disabled"}
    candidate = next(
        (item for item in turn_urls() if item.startswith(("stun:", "turn:"))),
        "",
    )
    if not candidate:
        return {
            "enabled": True,
            "status": "failed",
            "error": "没有可探测的 UDP STUN/TURN URL",
        }
    host, port = _host_port(candidate)
    transaction_id = os.urandom(12)
    request = struct.pack("!HHI12s", 0x0001, 0, _MAGIC_COOKIE, transaction_id)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(request, (host, port))
            response, _peer = sock.recvfrom(2048)
        if len(response) < 20:
            raise OSError("STUN response too short")
        msg_type, _length, cookie, response_tx = struct.unpack(
            "!HHI12s", response[:20]
        )
        if msg_type != 0x0101 or cookie != _MAGIC_COOKIE or response_tx != transaction_id:
            raise OSError("invalid STUN binding response")
        return {
            "enabled": True,
            "status": "ok",
            "host": host,
            "port": port,
        }
    except (OSError, ValueError) as exc:
        return {
            "enabled": True,
            "status": "failed",
            "host": host,
            "port": port,
            "error": str(exc),
        }
