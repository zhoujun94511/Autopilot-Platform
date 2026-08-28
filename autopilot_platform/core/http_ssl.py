"""httpx 客户端 TLS 校验（Runner / 连 Platform 的 HTTP 客户端）。"""

from __future__ import annotations

import os
from pathlib import Path


def httpx_verify() -> bool | str:
    """``AUTOPILOT_SSL_VERIFY``（默认开）；企业 CA 用 ``AUTOPILOT_SSL_CA_FILE``。"""
    raw = (os.environ.get("AUTOPILOT_SSL_VERIFY") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    ca = (os.environ.get("AUTOPILOT_SSL_CA_FILE") or "").strip()
    if ca:
        path = Path(ca).expanduser()
        if path.is_file():
            return str(path.resolve())
    return True
