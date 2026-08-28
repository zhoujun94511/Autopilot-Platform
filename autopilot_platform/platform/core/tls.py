"""Platform TLS / 反向代理 HTTPS 配置。

两种生产 HTTPS 模式（二选一或组合）：

1. **直连 TLS**：配置 ``MC_SSL_CERTFILE`` + ``MC_SSL_KEYFILE``，uvicorn 终结 HTTPS。
2. **反代 TLS**：nginx / Caddy 等终结 HTTPS，Platform 本机 HTTP + ``MC_BEHIND_HTTPS_PROXY=1``。

开发联调：
  - HTTP：``start_dev.py``（默认 :8000）
  - HTTPS 直连 TLS：``start_dev_https.py``（默认 :8443，需 MC_SSL_* 或 ``--auto-cert``）
  生产请用 ``python -m autopilot_platform.platform``，不用上述联调脚本。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _file_env(name: str) -> Path | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def ssl_certfile() -> Path | None:
    return _file_env("MC_SSL_CERTFILE")


def ssl_keyfile() -> Path | None:
    return _file_env("MC_SSL_KEYFILE")


def ssl_ca_certs() -> Path | None:
    return _file_env("MC_SSL_CA_CERTS")


def ssl_enabled() -> bool:
    """证书与私钥文件均存在且可读时启用直连 TLS（可被 MC_SSL_ENABLED=0 显式关闭）。"""
    flag = (os.environ.get("MC_SSL_ENABLED") or "").strip().lower()
    cert = ssl_certfile()
    key = ssl_keyfile()
    if cert is not None and key is not None:
        if flag in ("0", "false", "no", "off"):
            return False
        return True
    if flag in ("1", "true", "yes", "on"):
        return cert is not None and key is not None
    return False


def behind_https_proxy() -> bool:
    """TLS 由前置反向代理终结；Platform 仍监听 HTTP，但对外 URL 为 https://。"""
    return (os.environ.get("MC_BEHIND_HTTPS_PROXY") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def forwarded_allow_ips() -> str:
    """受信反代 IP（uvicorn ``forwarded_allow_ips``），默认仅本机。"""
    return (os.environ.get("MC_FORWARDED_ALLOW_IPS") or "127.0.0.1").strip() or "127.0.0.1"


def uvicorn_ssl_kwargs() -> dict[str, Any]:
    if not ssl_enabled():
        return {}
    cert = ssl_certfile()
    key = ssl_keyfile()
    if cert is None or key is None:
        return {}
    out: dict[str, Any] = {
        "ssl_certfile": str(cert.resolve()),
        "ssl_keyfile": str(key.resolve()),
    }
    ca = ssl_ca_certs()
    if ca is not None:
        out["ssl_ca_certs"] = str(ca.resolve())
    return out


def uvicorn_proxy_kwargs() -> dict[str, Any]:
    if not behind_https_proxy():
        return {}
    return {
        "proxy_headers": True,
        "forwarded_allow_ips": forwarded_allow_ips(),
    }


def validate_tls_files() -> tuple[str, ...]:
    """启动前校验：显式要求 TLS 或配置了路径但文件缺失。"""
    flag = (os.environ.get("MC_SSL_ENABLED") or "").strip().lower()
    cert_path = (os.environ.get("MC_SSL_CERTFILE") or "").strip()
    key_path = (os.environ.get("MC_SSL_KEYFILE") or "").strip()
    errors: list[str] = []

    if flag in ("1", "true", "yes", "on"):
        if not cert_path or not key_path:
            errors.append("MC_SSL_ENABLED=1 时必须同时设置 MC_SSL_CERTFILE 与 MC_SSL_KEYFILE")
        else:
            if ssl_certfile() is None:
                errors.append(f"MC_SSL_CERTFILE 不是可读文件：{cert_path}")
            if ssl_keyfile() is None:
                errors.append(f"MC_SSL_KEYFILE 不是可读文件：{key_path}")

    if cert_path and ssl_certfile() is None:
        errors.append(f"MC_SSL_CERTFILE 不是可读文件：{cert_path}")
    if key_path and ssl_keyfile() is None:
        errors.append(f"MC_SSL_KEYFILE 不是可读文件：{key_path}")
    if (cert_path and not key_path) or (key_path and not cert_path):
        errors.append("MC_SSL_CERTFILE 与 MC_SSL_KEYFILE 必须成对配置")

    return tuple(errors)


def https_serving_configured() -> bool:
    return ssl_enabled() or behind_https_proxy()


def production_https_errors() -> tuple[str, ...]:
    """对外 URL 为 https:// 时，须启用直连 TLS 或反代模式。"""
    from .settings import is_production
    from .urls import platform_base_url

    if not is_production():
        return ()
    if validate_tls_files():
        return validate_tls_files()
    base = (platform_base_url() or "").strip().lower()
    if not base.startswith("https://"):
        return ()
    if https_serving_configured():
        return ()
    return (
        "对外 Platform URL 为 https://，但未配置 HTTPS："
        "设置 MC_SSL_CERTFILE + MC_SSL_KEYFILE（直连 TLS），"
        "或 MC_BEHIND_HTTPS_PROXY=1（反代终结 TLS，见 docs/setup/https.md）",
    )
