"""Platform 基址与 CORS 派生 URL（单一真源）。

优先级（网络 bootstrap 层，仅 env + 代码默认）：
  ``MC_PLATFORM_URL`` / ``MC_SERVER`` / ``MC_MANAGED_RUNNER_SERVER``（显式 URL）
  → ``MC_HOST`` + ``MC_PORT``
  → 代码默认 ``http://127.0.0.1:8000``

运维 JSON（``runtime_config``）不参与监听地址；可配 ``MC_DESIGN_WEBHOOK_URL`` 等回调。
"""

from __future__ import annotations

import os


def _loopback_host(host: str) -> str:
    h = (host or "127.0.0.1").strip() or "127.0.0.1"
    if h in ("0.0.0.0", "::"):
        return "127.0.0.1"
    return h


def platform_host() -> str:
    return _loopback_host(os.environ.get("MC_HOST", "127.0.0.1"))


def platform_port() -> int:
    raw = (os.environ.get("MC_PORT", "8000") or "8000").strip()
    try:
        return int(raw)
    except ValueError:
        return 8000


def platform_base_url() -> str:
    """Runner / MCP / SSO 默认回落用的 Platform 根 URL（无尾斜杠）。"""
    for key in (
        "AUTOPILOT_PLATFORM_URL",
        "MC_PLATFORM_URL",
        "MC_SERVER",
        "MC_MANAGED_RUNNER_SERVER",
    ):
        raw = (os.environ.get(key) or "").strip().rstrip("/")
        if raw:
            return raw
    host = platform_host()
    port = platform_port()
    return f"http://{host}:{port}"


def default_cors_origins() -> list[str]:
    """未设 ``MC_CORS_ORIGINS`` 时的开发默认。"""
    port = platform_port()
    bases = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
    explicit = (
        (os.environ.get("AUTOPILOT_PLATFORM_URL") or "")
        or (os.environ.get("MC_PLATFORM_URL") or "")
        or (os.environ.get("MC_SERVER") or "")
    ).strip().rstrip("/")
    if explicit:
        bases.add(explicit)
    return sorted(bases)
