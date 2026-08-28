"""平台配置：令牌、JWT、数据库、制品目录。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TextIO

from autopilot_platform.core.constants import DEFAULT_API_TOKEN

from .urls import platform_base_url


def _cfg_str(key: str, env_default: str = "") -> str:
    from ..ops.runtime_config import cfg_str as _runtime_cfg_str  # 延迟：runtime_config 会 import settings

    return _runtime_cfg_str(key, env_default)


def _cfg_bool(key: str, env_default: str = "1") -> bool:
    from ..ops.runtime_config import cfg_bool as _runtime_cfg_bool  # 延迟：runtime_config 会 import settings

    return _runtime_cfg_bool(key, env_default)


def _cfg_int(key: str, env_default: str, *, minimum: int | None = None) -> int:
    from ..ops.runtime_config import cfg_int as _runtime_cfg_int  # 延迟：runtime_config 会 import settings

    return _runtime_cfg_int(key, env_default, minimum=minimum)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_LEGACY_DATA_DIR = _REPO_ROOT / "autopilot_platform" / "data"


def legacy_data_dir() -> Path:
    """旧版默认数据目录 ``autopilot_platform/data/``（仅迁移工具使用）。"""
    return _LEGACY_DATA_DIR


def default_data_dir() -> Path:
    """未设 ``MC_DATA_DIR`` 时的统一默认目录（仓库根 ``data/``）。"""
    return _REPO_ROOT / "data"


def data_dir() -> Path:
    """Platform 运行时数据根目录。

    默认 ``<仓库根>/data/``（库、mc_runtime_config、向量索引、制品等均在树下）。
    可用 ``MC_DATA_DIR`` 覆盖。若未覆盖且仅存在旧路径 ``autopilot_platform/data/``，
    暂读旧路径并在 stderr 提示执行 ``init_platform.py migrate-data``。
    """
    raw = os.environ.get("MC_DATA_DIR", "").strip()
    if raw:
        root = Path(raw)
    else:
        unified = default_data_dir()
        if not (unified / "autopilot_platform.db").is_file():
            legacy_db = _LEGACY_DATA_DIR / "autopilot_platform.db"
            if legacy_db.is_file():
                import sys

                print(
                    "WARN: 仍在使用 autopilot_platform/data/；"
                    "请运行: python tools/init_platform.py migrate-data --yes",
                    file=sys.stderr,
                )
                root = _LEGACY_DATA_DIR
            else:
                root = unified
        else:
            root = unified
    root.mkdir(parents=True, exist_ok=True)
    return root


def api_token() -> str:
    """Runner / 执行通道全局 ``X-API-Token``（``MC_API_TOKEN``）。

    与 ``MC_ADMIN_API_TOKEN`` 拆分后，本令牌 **不得** 升为平台 admin（role=runner）。
    """
    return os.environ.get("MC_API_TOKEN", DEFAULT_API_TOKEN).strip() or DEFAULT_API_TOKEN


def admin_api_token() -> str:
    """运维专用令牌（``MC_ADMIN_API_TOKEN``）。

    策略：
    - **已设置**：仅本令牌具备 admin；``MC_API_TOKEN`` / 独立 Runner Token 均为执行通道。
    - **未设置**：全局 ``MC_API_TOKEN`` **默认仅为 runner**；仅当显式
      ``MC_ALLOW_LEGACY_TOKEN_ADMIN=1`` 时才兼容升为 admin（迁移逃生口）。
    """
    return os.environ.get("MC_ADMIN_API_TOKEN", "").strip()


def allow_legacy_token_admin() -> bool:
    """是否允许「未配置 MC_ADMIN_API_TOKEN 时，全局 MC_API_TOKEN 升为 admin」。

    默认 **关闭**（secure-by-default）。旧联调 / 迁移须显式::

        MC_ALLOW_LEGACY_TOKEN_ADMIN=1
    """
    v = os.environ.get("MC_ALLOW_LEGACY_TOKEN_ADMIN", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def is_production() -> bool:
    """``MC_ENV=prod|production`` 视为生产。"""
    return os.environ.get("MC_ENV", "").strip().lower() in ("prod", "production")


def is_loopback_bind_host(host: str | None = None) -> bool:
    """监听地址是否视为仅本机（允许开发默认凭据）。

    ``0.0.0.0`` / ``::`` 会暴露到局域网，**不算** loopback。
    """
    raw = (host if host is not None else os.environ.get("MC_HOST", "127.0.0.1")).strip()
    h = raw.lower()
    if not h:
        return True
    if h in ("127.0.0.1", "::1", "localhost"):
        return True
    if h in ("0.0.0.0", "::", "[::]"):
        return False
    try:
        import ipaddress

        ip = ipaddress.ip_address(h.strip("[]"))
        return bool(ip.is_loopback)
    except ValueError:
        # 主机名（非 IP）：保守视为对外暴露
        return False


def is_exposed_bind_host(host: str | None = None) -> bool:
    """``MC_HOST`` / 实际监听地址是否可能对外可达。"""
    return not is_loopback_bind_host(host)


def allow_managed_runner() -> bool:
    """是否允许 Platform 进程托管本机 Runner（Web 启停）。

    Secure-by-default（AUD-P1-004）：

    - 须显式 ``MC_ALLOW_MANAGED_RUNNER=1|true|yes|on``（未设置 / ``0`` → 关）
    - 且 ``MC_HOST`` 为 loopback（``127.0.0.1`` / ``::1`` / ``localhost``）
    - 非 loopback（``0.0.0.0`` / LAN / ``--lan``）一律禁止：远程会话不可 Web→本机 spawn
    """
    raw = os.environ.get("MC_ALLOW_MANAGED_RUNNER", "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return False
    if is_exposed_bind_host():
        return False
    return True


def managed_runner_deny_message() -> str:
    """``allow_managed_runner()`` 为假时的操作者可读原因。"""
    from . import api_messages as msg

    raw = os.environ.get("MC_ALLOW_MANAGED_RUNNER", "").strip().lower()
    if raw in ("1", "true", "yes", "on") and is_exposed_bind_host():
        return msg.MANAGED_RUNNER_EXPOSED_BIND
    return msg.MANAGED_RUNNER_DISABLED


def managed_runner_id() -> str:
    """托管 Runner 的固定 ``runner_id``（默认 ``managed-local``）。"""
    return (
        os.environ.get("MC_MANAGED_RUNNER_ID", "managed-local").strip() or "managed-local"
    )


def managed_runner_server() -> str:
    """托管 Runner 连接的 Platform URL（``MC_MANAGED_RUNNER_SERVER`` 或 ``platform_base_url()``）。"""
    raw = os.environ.get("MC_MANAGED_RUNNER_SERVER", "").strip()
    if raw:
        return raw.rstrip("/")
    return platform_base_url()


def platform_public_base_url() -> str:
    """供运维配置中心展示的 Platform 基址（bootstrap 层，非 runtime JSON）。"""
    return platform_base_url()


def require_admin_token_split() -> bool:
    """生产或显式开关要求必须配置独立 ``MC_ADMIN_API_TOKEN``。

    ``MC_REQUIRE_ADMIN_API_TOKEN=1`` 或 ``MC_ENV=production`` 时为真。
    为真且未配置 ADMIN token 时，启动打 ERROR（不阻断进程，避免半迁移部署无法拉起）。
    """
    if is_production():
        return True
    v = os.environ.get("MC_REQUIRE_ADMIN_API_TOKEN", "").strip().lower()
    return v in ("1", "true", "yes", "on")


_DEFAULT_JWT_SECRET = "dev-mc-jwt-secret-change-me-32b!!"


def jwt_secret() -> str:
    return (
        os.environ.get("MC_JWT_SECRET", _DEFAULT_JWT_SECRET).strip()
        or _DEFAULT_JWT_SECRET
    )


def turn_enabled() -> bool:
    return os.environ.get("MC_TURN_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def turn_urls() -> tuple[str, ...]:
    raw = os.environ.get(
        "MC_TURN_URLS",
        "stun:stun.l.google.com:19302",
    )
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def turn_secret() -> str:
    return os.environ.get("MC_TURN_SECRET", "").strip()


def turn_realm() -> str:
    return os.environ.get("MC_TURN_REALM", "autopilot.local").strip() or "autopilot.local"


def turn_credential_ttl_seconds() -> int:
    try:
        return max(
            60,
            min(
                86_400,
                int(os.environ.get("MC_TURN_CREDENTIAL_TTL_SEC", "3600")),
            ),
        )
    except ValueError:
        return 3600


def turn_username_prefix() -> str:
    raw = os.environ.get("MC_TURN_USERNAME_PREFIX", "autopilot").strip()
    return raw or "autopilot"


def using_insecure_defaults() -> bool:
    """开发默认口令/密钥是否仍在使用（生产应全部覆盖）。"""
    if api_token() == DEFAULT_API_TOKEN:
        return True
    if jwt_secret() == _DEFAULT_JWT_SECRET:
        return True
    if bootstrap_admin_password() == "admin":
        return True
    return False


def insecure_defaults_reasons() -> tuple[str, ...]:
    """开发默认凭据仍在使用时的可读原因（不含 ADMIN Token 拆分项）。"""
    reasons: list[str] = []
    if api_token() == DEFAULT_API_TOKEN:
        reasons.append("MC_API_TOKEN 仍为默认值 (dev-mc-token)")
    if jwt_secret() == _DEFAULT_JWT_SECRET:
        reasons.append("MC_JWT_SECRET 仍为默认值")
    if bootstrap_admin_password() == "admin":
        reasons.append("MC_ADMIN_PASSWORD 仍为默认值 (admin)")
    return tuple(reasons)


def emit_insecure_defaults_startup_banner(*, stream: TextIO | None = None) -> bool:
    """向 stderr 打印醒目横幅（AUD-2026-06）；有默认凭据时返回 True。

    硬门禁仍由 ``validate_production_security`` / ``validate_bind_security`` 负责；
    本函数只提升 loopback 开发场景的可见性，不替代校验。
    """
    if not using_insecure_defaults():
        return False
    import sys  # 延迟：仅打印启动横幅时要 stderr

    out = stream if stream is not None else sys.stderr
    reasons = insecure_defaults_reasons()
    lines = [
        "",
        "=" * 72,
        " WARNING: AutoPilot Platform is using INSECURE DEVELOPMENT DEFAULTS",
        " (AUD-2026-06). Safe only on loopback; production / non-loopback binds",
        " are rejected by validate_production_security / validate_bind_security.",
        " Reasons:",
    ]
    for reason in reasons:
        lines.append(f"   - {reason}")
    lines.extend(
        [
            " Fix: copy deploy/production.env.example → .env, set strong secrets,",
            "      MC_ENV=production, and a distinct MC_ADMIN_API_TOKEN.",
            "=" * 72,
            "",
        ]
    )
    print("\n".join(lines), file=out, flush=True)
    return True


def production_security_errors() -> tuple[str, ...]:
    """返回阻止生产启动的凭据配置问题；开发环境由调用方仅告警。"""
    errors: list[str] = []
    if api_token() == DEFAULT_API_TOKEN:
        errors.append("MC_API_TOKEN 仍为默认值")
    if jwt_secret() == _DEFAULT_JWT_SECRET:
        errors.append("MC_JWT_SECRET 仍为默认值")
    if bootstrap_admin_password() == "admin":
        errors.append("MC_ADMIN_PASSWORD 仍为默认值")
    admin_token = admin_api_token()
    if not admin_token:
        errors.append("MC_ADMIN_API_TOKEN 未配置")
    elif admin_token == api_token():
        errors.append("MC_ADMIN_API_TOKEN 必须与 MC_API_TOKEN 不同")
    if turn_enabled():
        secret = turn_secret()
        if len(secret) < 32:
            errors.append("MC_TURN_ENABLED=1 时 MC_TURN_SECRET 至少 32 字节")
        if not any(url.startswith(("turn:", "turns:")) for url in turn_urls()):
            errors.append("MC_TURN_ENABLED=1 时 MC_TURN_URLS 必须包含 turn: 或 turns:")
    if is_production() and not (os.environ.get("MC_CORS_ORIGINS") or "").strip():
        errors.append("MC_CORS_ORIGINS 未配置（生产须显式允许跨域源）")
    from .tls import production_https_errors, validate_tls_files

    errors.extend(validate_tls_files())
    errors.extend(production_https_errors())
    return tuple(errors)


def validate_production_security() -> None:
    """生产配置必须使用强凭据并拆分 Runner/Admin Token。"""
    if not is_production():
        return
    errors = production_security_errors()
    if errors:
        raise RuntimeError("生产安全配置校验失败：" + "；".join(errors))


def validate_bind_security(host: str | None = None) -> None:
    """非 loopback 绑定时强制与生产同等凭据强度（不依赖 ``MC_ENV``）。

    避免 ``MC_HOST=0.0.0.0`` / ``start_dev --lan`` 带着默认 ``dev-mc-token`` 暴露到局域网。
    实际监听 host 应写入 ``MC_HOST``（见 ``platform.__main__`` / ``start_dev``）。
    """
    if not is_exposed_bind_host(host):
        return
    errors = production_security_errors()
    if errors:
        raise RuntimeError(
            "非 loopback 绑定禁止不安全默认凭据或未拆分 ADMIN Token："
            + "；".join(errors)
            + "。请改强密钥并设置独立 MC_ADMIN_API_TOKEN，或仅绑定 127.0.0.1。"
        )


def artifact_max_mb() -> int:
    """工程制品 zip 上传上限（MB）；0=不限。"""
    return _cfg_int("MC_ARTIFACT_MAX_MB", "512", minimum=0)


def jwt_expire_hours() -> int:
    try:
        return max(1, int(os.environ.get("MC_JWT_EXPIRE_HOURS", "72")))
    except ValueError:
        return 72


def access_token_minutes() -> int:
    """Access JWT 有效期（分钟）。

    优先 ``MC_ACCESS_TOKEN_MINUTES``；否则若显式设了 ``MC_JWT_EXPIRE_HOURS`` 则换算；
    默认 60（配合 refresh token）。
    """
    raw = os.environ.get("MC_ACCESS_TOKEN_MINUTES", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    if os.environ.get("MC_JWT_EXPIRE_HOURS", "").strip():
        return max(1, jwt_expire_hours() * 60)
    return 60


def stream_token_minutes() -> int:
    """Job 日志 SSE 短时票有效期（分钟）；默认 2，上限 15。

    ``MC_STREAM_TOKEN_MINUTES`` 可调。票仅绑定单一 job_id，经 Query 传给 EventSource。
    """
    raw = os.environ.get("MC_STREAM_TOKEN_MINUTES", "").strip()
    if raw:
        try:
            return max(1, min(15, int(raw)))
        except ValueError:
            pass
    return 2


def refresh_token_days() -> int:
    try:
        return max(1, int(os.environ.get("MC_REFRESH_TOKEN_DAYS", "14")))
    except ValueError:
        return 14


def bootstrap_admin_username() -> str:
    return os.environ.get("MC_ADMIN_USER", "admin").strip() or "admin"


def bootstrap_admin_password() -> str:
    return os.environ.get("MC_ADMIN_PASSWORD", "admin").strip() or "admin"


def database_url() -> str:
    raw = os.environ.get("MC_DATABASE_URL", "").strip()
    if raw:
        return raw
    db_path = data_dir() / "autopilot_platform.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def artifacts_root() -> Path:
    raw = os.environ.get("MC_ARTIFACTS_DIR", "").strip()
    root = Path(raw) if raw else (data_dir() / "artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def app_builds_root() -> Path:
    """应用包（apk/ipa）独立存储根，与工程制品分离。"""
    raw = os.environ.get("MC_APP_BUILDS_DIR", "").strip()
    root = Path(raw) if raw else (data_dir() / "app_builds")
    root.mkdir(parents=True, exist_ok=True)
    return root


def reports_root() -> Path:
    raw = os.environ.get("MC_REPORTS_DIR", "").strip()
    root = Path(raw) if raw else (data_dir() / "reports")
    root.mkdir(parents=True, exist_ok=True)
    return root


def design_uploads_root() -> Path:
    raw = os.environ.get("AP_DESIGN_UPLOADS_DIR", "").strip()
    root = Path(raw) if raw else (data_dir() / "design_uploads")
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_logs_root() -> Path:
    raw = os.environ.get("MC_JOB_LOGS_DIR", "").strip()
    root = Path(raw) if raw else (data_dir() / "job_logs")
    root.mkdir(parents=True, exist_ok=True)
    return root


def platform_logs_root() -> Path:
    """Platform / 托管 Runner 等服务端日志目录（默认仓库根 ``logs/``）。"""
    raw = os.environ.get("MC_PLATFORM_LOGS_DIR", "").strip()
    if raw:
        root = Path(raw)
    else:
        # settings.py → …/autopilot_platform/platform/core/settings.py → parents[3] = 仓库根
        root = Path(__file__).resolve().parents[3] / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_level() -> int:
    """``MC_LOG_LEVEL``：DEBUG | INFO | WARNING | ERROR（默认 INFO）。"""
    raw = os.environ.get("MC_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def log_format() -> str:
    """``MC_LOG_FORMAT``：text（默认）| json。"""
    raw = os.environ.get("MC_LOG_FORMAT", "text").strip().lower()
    return raw if raw in ("text", "json") else "text"


def storage_backend() -> str:
    """local（默认）| s3。"""
    v = os.environ.get("MC_STORAGE", "local").strip().lower()
    return v if v in ("local", "s3") else "local"


def s3_bucket() -> str:
    return os.environ.get("MC_S3_BUCKET", "").strip()


def s3_prefix() -> str:
    p = os.environ.get("MC_S3_PREFIX", "mc-artifacts/").strip() or "mc-artifacts/"
    return p if p.endswith("/") else p + "/"


def webhook_url() -> str:
    """任务终态全局回调；空则不发。可被任务字段 webhook_url 覆盖。"""
    return _cfg_str("MC_WEBHOOK_URL", "")


def webhook_secret() -> str:
    """可选 HMAC-SHA256 签名密钥 → 请求头 X-MC-Signature: sha256=..."""
    return _cfg_str("MC_WEBHOOK_SECRET", "")


def design_webhook_use_job_url() -> bool:
    return _cfg_str("MC_DESIGN_WEBHOOK_USE_JOB_URL", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def design_webhook_url() -> str:
    """逻辑/意图用例 APPROVED 时推送。

    优先 ``MC_DESIGN_WEBHOOK_URL``；
    若为空且 ``MC_DESIGN_WEBHOOK_USE_JOB_URL=1``，则兜底复用 ``MC_WEBHOOK_URL``；
    否则空字符串（不推送）。
    """
    explicit = _cfg_str("MC_DESIGN_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit
    if design_webhook_use_job_url():
        return webhook_url()
    return ""


def artifact_retention_days() -> int:
    """默认保留天数（purge 未指定时使用）；0 表示不按天自动限。"""
    return _cfg_int("MC_ARTIFACT_RETENTION_DAYS", "30", minimum=0)


def app_build_retention_days() -> int:
    """应用资源默认保留天数；0 表示不按天清理。"""
    return _cfg_int("MC_APP_BUILD_RETENTION_DAYS", "90", minimum=0)


def job_report_retention_days() -> int:
    """Job 报告目录（HTML/result/evidence）默认保留天数；0=不按天清理。"""
    return _cfg_int("MC_JOB_REPORT_RETENTION_DAYS", "90", minimum=0)


def job_log_retention_days() -> int:
    """终态 Job 的 ``data/job_logs/*.log`` 默认保留天数；0=不按天清理。"""
    return _cfg_int("MC_JOB_LOG_RETENTION_DAYS", "90", minimum=0)


def audit_log_retention_days() -> int:
    """DB ``audit_logs`` 默认保留天数；0=不按天清理。"""
    return _cfg_int("MC_AUDIT_LOG_RETENTION_DAYS", "180", minimum=0)


def app_build_max_mb() -> int:
    """单包上传上限（MB）；0=不限。"""
    return _cfg_int("MC_APP_BUILD_MAX_MB", "512", minimum=0)


def job_report_max_mb() -> int:
    """单个报告 HTML/result.json 上传上限（MB）；0=不限。"""
    return _cfg_int("MC_JOB_REPORT_MAX_MB", "64", minimum=0)


def app_build_max_count_per_project() -> int:
    """单项目空间应用资源条数上限；0=不限。"""
    return _cfg_int("MC_APP_BUILD_MAX_COUNT", "100", minimum=0)


def app_build_max_total_mb_per_project() -> int:
    """单项目空间应用资源总容量上限（MB）；0=不限。"""
    return _cfg_int("MC_APP_BUILD_MAX_TOTAL_MB", "10240", minimum=0)


def schedule_tick_sec() -> int:
    try:
        return max(5, int(os.environ.get("MC_SCHEDULE_TICK_SEC", "15")))
    except ValueError:
        return 15


def schedule_loop_enabled() -> bool:
    v = os.environ.get("MC_SCHEDULE_ENABLED", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def oidc_enabled() -> bool:
    v = os.environ.get("MC_OIDC_ENABLED", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def oidc_issuer() -> str:
    return os.environ.get("MC_OIDC_ISSUER", "").strip().rstrip("/")


def oidc_client_id() -> str:
    return os.environ.get("MC_OIDC_CLIENT_ID", "").strip()


def oidc_client_secret() -> str:
    return os.environ.get("MC_OIDC_CLIENT_SECRET", "").strip()


def oidc_redirect_uri() -> str:
    default = f"{platform_base_url()}/api/v1/auth/oidc/callback"
    return os.environ.get("MC_OIDC_REDIRECT_URI", default).strip() or default


def oidc_scopes() -> str:
    return os.environ.get("MC_OIDC_SCOPES", "openid profile email").strip() or "openid profile email"


def oidc_auto_provision() -> bool:
    v = os.environ.get("MC_OIDC_AUTO_PROVISION", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def oidc_default_role() -> str:
    r = os.environ.get("MC_OIDC_DEFAULT_ROLE", "operator").strip() or "operator"
    return r if r in ("admin", "operator") else "operator"


def oidc_frontend_redirect() -> str:
    """登录成功后带回 JWT 的前端地址。"""
    return os.environ.get(
        "MC_OIDC_FRONTEND_REDIRECT", "http://127.0.0.1:5173/"
    ).strip() or "http://127.0.0.1:5173/"


def saml_enabled() -> bool:
    v = os.environ.get("MC_SAML_ENABLED", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def saml_idp_sso_url() -> str:
    return os.environ.get("MC_SAML_IDP_SSO_URL", "").strip()


def saml_idp_entity_id() -> str:
    return os.environ.get("MC_SAML_IDP_ENTITY_ID", "").strip()


def saml_sp_entity_id() -> str:
    default = f"{platform_base_url()}/api/v1/auth/saml/metadata"
    return os.environ.get("MC_SAML_SP_ENTITY_ID", default).strip() or default


def saml_acs_url() -> str:
    default = f"{platform_base_url()}/api/v1/auth/saml/acs"
    return os.environ.get("MC_SAML_ACS_URL", default).strip() or default


def saml_frontend_redirect() -> str:
    return os.environ.get(
        "MC_SAML_FRONTEND_REDIRECT",
        os.environ.get("MC_OIDC_FRONTEND_REDIRECT", "http://127.0.0.1:5173/"),
    ).strip() or "http://127.0.0.1:5173/"


def saml_auto_provision() -> bool:
    v = os.environ.get("MC_SAML_AUTO_PROVISION", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def saml_default_role() -> str:
    r = os.environ.get("MC_SAML_DEFAULT_ROLE", "operator").strip() or "operator"
    return r if r in ("admin", "operator") else "operator"


def saml_allow_unsigned() -> bool:
    """仅联调/单测：允许未签名 Assertion（生产务必关闭）。"""
    v = os.environ.get("MC_SAML_ALLOW_UNSIGNED", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def saml_idp_cert_pem() -> str:
    """IdP 签名校验证书 PEM。优先 MC_SAML_IDP_CERT（可含 \\n），否则读 MC_SAML_IDP_CERT_FILE。"""
    raw = os.environ.get("MC_SAML_IDP_CERT", "").strip()
    if raw:
        pem = raw.replace("\\n", "\n")
        if "BEGIN CERTIFICATE" in pem:
            return pem if pem.endswith("\n") else pem + "\n"
    path = os.environ.get("MC_SAML_IDP_CERT_FILE", "").strip()
    if not path and raw:
        from pathlib import Path

        p = Path(raw)
        if p.is_file():
            path = str(p)
    if path:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8")
    return ""


def saml_clock_skew_sec() -> int:
    """Conditions NotBefore/NotOnOrAfter 允许时钟偏差（秒）。"""
    try:
        return max(0, int(os.environ.get("MC_SAML_CLOCK_SKEW_SEC", "120")))
    except ValueError:
        return 120


def job_stale_sec() -> int:
    """claimed/running 超过该秒数视为僵死，可被回收。0=关闭。"""
    return _cfg_int("MC_JOB_STALE_SEC", "3600", minimum=0)


def alert_webhook_url() -> str:
    """运维告警推送 URL（失败任务 / 僵死回收等）；空则不发。"""
    return _cfg_str("MC_ALERT_WEBHOOK_URL", "")


def alert_channel() -> str:
    """告警载荷格式：json（默认）| dingtalk | feishu | slack。"""
    v = _cfg_str("MC_ALERT_CHANNEL", "json").lower() or "json"
    if v in ("ding", "dingding"):
        v = "dingtalk"
    if v in ("lark",):
        v = "feishu"
    return v if v in ("json", "dingtalk", "feishu", "slack") else "json"


def alert_secret() -> str:
    """钉钉/飞书机器人加签密钥（SEC…）；空则不加签。"""
    return _cfg_str("MC_ALERT_SECRET", "")


def alert_on_failed() -> bool:
    return _cfg_bool("MC_ALERT_ON_FAILED", "1")


def alert_on_stale() -> bool:
    return _cfg_bool("MC_ALERT_ON_STALE", "1")


def alert_on_runner_offline() -> bool:
    """Runner 由在线变为离线时是否发运维告警。"""
    return _cfg_bool("MC_ALERT_ON_RUNNER_OFFLINE", "1")


def alert_runner_offline_cooldown_sec() -> int:
    """同一 Runner 离线告警冷却（秒），默认 1h。"""
    return _cfg_int("MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC", "3600", minimum=60)


def alert_on_device_empty() -> bool:
    """在线设备池由非空变为空（且仍有 Runner 在线）时是否告警。"""
    return _cfg_bool("MC_ALERT_ON_DEVICE_EMPTY", "1")


def metrics_enabled() -> bool:
    return _cfg_bool("MC_METRICS_ENABLED", "1")


def require_job_devices() -> bool:
    """为真时创建 Job 必须指定 device_udids（默认关；platform=web 豁免）。"""
    return _cfg_bool("MC_REQUIRE_JOB_DEVICES", "0")


def require_artifact_manifest() -> bool:
    """为真时上传制品要求 manifest=valid（默认关，仅记录状态不阻断）。"""
    return _cfg_bool("MC_REQUIRE_ARTIFACT_MANIFEST", "0")


def enforce_runtime_version() -> bool:
    """为真时创建 Job：制品 required_runtime_version 与 ap 执行核不兼容则拒绝。"""
    return is_production() or _cfg_bool("MC_ENFORCE_RUNTIME_VERSION", "0")
