"""公开 Bootstrap：前端 / IDE 启动时拉取 Platform 基址与 API 路径（无密钥）。"""

from __future__ import annotations

import os
from typing import Any

from autopilot_platform.core.constants import API_V1_PREFIX

from ..core import settings as mc_settings
from ..core import tls as mc_tls


def _runner_module() -> str:
    return (
        os.environ.get("MC_RUNNER_MODULE", "autopilot_platform.runner").strip()
        or "autopilot_platform.runner"
    )


def runner_cli_command(*, mask_token: bool = True, runner_id: str = "") -> str:
    """公开 Runner CLI 示例；不把真实 Token 写入可复制命令（AUD-2026-01）。

    ``mask_token`` 保留调用方兼容；曾为 False 时会回显全局 ``MC_API_TOKEN``，已禁止。
    """
    _ = mask_token
    rid = (runner_id or "").strip() or "my-runner"
    server = mc_settings.managed_runner_server()
    return (
        f"python -m {_runner_module()} "
        f"--server {server} --token-env MC_RUNNER_TOKEN --runner-id {rid}"
    )


def build_public_bootstrap() -> dict[str, Any]:
    base = mc_settings.platform_public_base_url()
    prefix = API_V1_PREFIX.rstrip("/")
    return {
        "schema_version": "1",
        "platform_base_url": base,
        "api_prefix": prefix,
        "web_dev_port": 5173,
        "config_priority": "runtime_json > env > code_default",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "openapi": "/docs",
            "bootstrap": f"{prefix}/public/bootstrap",
            "login": f"{prefix}/auth/login",
            "refresh": f"{prefix}/auth/refresh",
            "me": f"{prefix}/auth/me",
            "ops_config": f"{prefix}/ops/config",
            "runners_managed": f"{prefix}/runners/managed",
        },
        "runner": {
            "module": _runner_module(),
            "cli_command": runner_cli_command(mask_token=True),
        },
        "flags": {
            "design_webhook_configured": bool(mc_settings.design_webhook_url()),
            "managed_runner_allowed": mc_settings.allow_managed_runner(),
            "metrics_enabled": mc_settings.metrics_enabled(),
            "production": mc_settings.is_production(),
            # AUD-2026-06：仅布尔提示，不回显任何密钥
            "insecure_defaults": mc_settings.using_insecure_defaults(),
            "bind_exposed": mc_settings.is_exposed_bind_host(),
            "tls_direct": mc_tls.ssl_enabled(),
            "behind_https_proxy": mc_tls.behind_https_proxy(),
            "public_scheme_https": base.strip().lower().startswith("https://"),
        },
    }
