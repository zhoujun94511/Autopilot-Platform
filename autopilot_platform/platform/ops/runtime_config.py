"""运行时可覆盖的运维配置（JSON 文件），优先于同名环境变量。

安全敏感项（MC_API_TOKEN / MC_JWT_SECRET / DB / SAML 证书等）不在此列，仍只读环境变量。
密钥类字段落盘为 Fernet 密文（enc:v1:…），内存中解密后使用。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from ..core.settings import data_dir

_lock = threading.RLock()
_cache: dict[str, Any] | None = None

_ENC_PREFIX = "enc:v1:"
# 与 platform.core.settings 开发默认 JWT 一致；禁止用作 at-rest 加密主密钥。
_INSECURE_DEV_JWT_SECRET = "dev-mc-jwt-secret-change-me-32b!!"

# 运维类键：Webhook / 告警 / 限额 / 调度约束等
OPS_CONFIG_KEYS: tuple[str, ...] = (
    "MC_WEBHOOK_URL",
    "MC_WEBHOOK_SECRET",
    "MC_DESIGN_WEBHOOK_URL",
    "MC_DESIGN_WEBHOOK_USE_JOB_URL",
    "MC_WEBHOOK_ALLOW_LOOPBACK",
    "MC_ALERT_WEBHOOK_URL",
    "MC_ALERT_CHANNEL",
    "MC_ALERT_SECRET",
    "MC_ALERT_ON_FAILED",
    "MC_ALERT_ON_STALE",
    "MC_ALERT_ON_RUNNER_OFFLINE",
    "MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC",
    "MC_ALERT_ON_DEVICE_EMPTY",
    "MC_JOB_STALE_SEC",
    "MC_ARTIFACT_RETENTION_DAYS",
    "MC_APP_BUILD_RETENTION_DAYS",
    "MC_JOB_REPORT_RETENTION_DAYS",
    "MC_APP_BUILD_MAX_MB",
    "MC_APP_BUILD_MAX_COUNT",
    "MC_APP_BUILD_MAX_TOTAL_MB",
    "MC_METRICS_ENABLED",
    "MC_REQUIRE_JOB_DEVICES",
    "MC_REQUIRE_ARTIFACT_MANIFEST",
    "MC_ENFORCE_RUNTIME_VERSION",
)

# 设计域键：AI / 向量 / RAG / 用例生成 / 性能（与运维同属 runtime_config）
DESIGN_CONFIG_KEYS: tuple[str, ...] = (
    "AP_AI_PROVIDER",
    "AP_AI_API_KEY",
    "AP_AI_BASE_URL",
    "AP_AI_MODEL",
    "AP_AI_PLANNING_MODEL",
    "AP_AI_LOCATE_MODEL",
    "AP_AI_TIMEOUT_SEC",
    "AP_AI_MAX_TOKENS",
    "AP_AI_CODEGEN_MAX_TOKENS",
    "AP_AI_TEMPERATURE",
    "AP_AI_REASONING_EFFORT",
    "AP_AI_DEEPSEEK_THINKING",
    "AP_AI_DEEPSEEK_REASONING_EFFORT",
    "AP_AI_CHAT_MAX_ATTEMPTS",
    "AP_AI_CODEGEN_MAX_ATTEMPTS",
    "AP_AI_DAILY_TOKEN_BUDGET",
    "AP_AI_PROJECT_DAILY_TOKEN_BUDGET",
    "AP_AI_ORG_DAILY_TOKEN_BUDGET",
    "AP_AI_ENFORCE_TOKEN_BUDGET",
    "AP_AI_EMBEDDING_MODEL",
    "AP_AI_REJECT_DEGRADED",
    "AP_RAG_EMBEDDER",
    "AP_RAG_TOP_K",
    "AP_RAG_SCORE_THRESHOLD",
    "AP_RAG_HYBRID",
    "AP_RAG_FTS_FACTOR",
    "AP_RAG_FTS_MAX_CANDIDATES",
    "AP_ENABLE_CASE_GENERATION_RAG",
    "AP_MAX_CASE_NUM",
    "AP_CONTENT_SIMILARITY_THRESHOLD",
    "AP_ENABLE_CONTENT_DEDUP",
    "AP_CONTENT_DEDUP_BATCH_SIZE",
    "AP_CHUNK_SIZE",
    "AP_MAX_WORKERS",
    "AP_ENABLE_PARALLEL_PROCESSING",
    "AP_ENABLE_STREAMING",
    "AP_MAX_MEMORY_MB",
    "AP_ENABLE_EXPERIMENTAL_ACTIONS",
)

# 运行时 JSON 允许落盘的全部键（运维 ∪ 设计）；前端统一入口为「运维」配置中心
EDITABLE_KEYS: tuple[str, ...] = OPS_CONFIG_KEYS + DESIGN_CONFIG_KEYS

# 统一配置中心分类（供 GET /ops/config；overview 无键，仅 UI 快照）
CONFIG_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "id": "overview",
        "title": "配置健康",
        "description": "Key / 模型 / 检索 / 回调是否就绪（只读）",
        "keys": [],
    },
    {
        "id": "ai_model",
        "title": "AI 接入",
        "description": "提供商、API 密钥与默认模型",
        "keys": [
            "AP_AI_PROVIDER",
            "AP_AI_API_KEY",
            "AP_AI_BASE_URL",
            "AP_AI_MODEL",
            "AP_AI_PLANNING_MODEL",
            "AP_AI_LOCATE_MODEL",
            "AP_AI_TIMEOUT_SEC",
            "AP_AI_MAX_TOKENS",
            "AP_AI_CODEGEN_MAX_TOKENS",
            "AP_AI_TEMPERATURE",
            "AP_AI_REASONING_EFFORT",
            "AP_AI_DEEPSEEK_THINKING",
            "AP_AI_DEEPSEEK_REASONING_EFFORT",
            "AP_AI_CHAT_MAX_ATTEMPTS",
            "AP_AI_CODEGEN_MAX_ATTEMPTS",
            "AP_AI_DAILY_TOKEN_BUDGET",
            "AP_AI_PROJECT_DAILY_TOKEN_BUDGET",
            "AP_AI_ORG_DAILY_TOKEN_BUDGET",
            "AP_AI_ENFORCE_TOKEN_BUDGET",
            "AP_AI_REJECT_DEGRADED",
        ],
    },
    {
        "id": "vector_rag",
        "title": "知识检索",
        "description": "检索参数（语料在知识库管理）",
        "keys": [
            "AP_AI_EMBEDDING_MODEL",
            "AP_RAG_EMBEDDER",
            "AP_RAG_TOP_K",
            "AP_RAG_SCORE_THRESHOLD",
            "AP_RAG_HYBRID",
            "AP_RAG_FTS_FACTOR",
            "AP_RAG_FTS_MAX_CANDIDATES",
            "AP_ENABLE_CASE_GENERATION_RAG",
        ],
    },
    {
        "id": "case_generation",
        "title": "用例生成",
        "description": "生成数量、去重与实验动作",
        "keys": [
            "AP_MAX_CASE_NUM",
            "AP_CONTENT_SIMILARITY_THRESHOLD",
            "AP_ENABLE_CONTENT_DEDUP",
            "AP_CONTENT_DEDUP_BATCH_SIZE",
            "AP_ENABLE_EXPERIMENTAL_ACTIONS",
        ],
    },
    {
        "id": "performance",
        "title": "性能与高级",
        "description": "一般无需改：并发、流式与上传上限",
        "keys": [
            "AP_CHUNK_SIZE",
            "AP_MAX_WORKERS",
            "AP_ENABLE_PARALLEL_PROCESSING",
            "AP_ENABLE_STREAMING",
            "AP_MAX_MEMORY_MB",
        ],
    },
    {
        "id": "webhook_alert",
        "title": "通知与回调",
        "description": "任务回调、设计事件与告警",
        "keys": [
            "MC_WEBHOOK_URL",
            "MC_WEBHOOK_SECRET",
            "MC_DESIGN_WEBHOOK_URL",
            "MC_DESIGN_WEBHOOK_USE_JOB_URL",
            "MC_WEBHOOK_ALLOW_LOOPBACK",
            "MC_ALERT_WEBHOOK_URL",
            "MC_ALERT_CHANNEL",
            "MC_ALERT_SECRET",
            "MC_ALERT_ON_FAILED",
            "MC_ALERT_ON_STALE",
            "MC_ALERT_ON_RUNNER_OFFLINE",
            "MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC",
            "MC_ALERT_ON_DEVICE_EMPTY",
        ],
    },
    {
        "id": "storage",
        "title": "存储与清理",
        "description": "僵死阈值与制品 / 应用包保留策略",
        "keys": [
            "MC_JOB_STALE_SEC",
            "MC_ARTIFACT_RETENTION_DAYS",
            "MC_APP_BUILD_RETENTION_DAYS",
            "MC_APP_BUILD_MAX_MB",
            "MC_APP_BUILD_MAX_COUNT",
            "MC_APP_BUILD_MAX_TOTAL_MB",
        ],
    },
    {
        "id": "devices_artifacts",
        "title": "调度与制品策略",
        "description": "设备约束、Manifest、运行时版本与 Metrics",
        "keys": [
            "MC_REQUIRE_JOB_DEVICES",
            "MC_REQUIRE_ARTIFACT_MANIFEST",
            "MC_ENFORCE_RUNTIME_VERSION",
            "MC_METRICS_ENABLED",
        ],
    },
)

# 设计 API 分类（GET /design/config；程序调用保留，前端不再单独入口）
DESIGN_CONFIG_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "id": "ai_model",
        "title": "AI 模型",
        "keys": [
            "AP_AI_PROVIDER",
            "AP_AI_API_KEY",
            "AP_AI_BASE_URL",
            "AP_AI_MODEL",
            "AP_AI_PLANNING_MODEL",
            "AP_AI_LOCATE_MODEL",
            "AP_AI_TIMEOUT_SEC",
            "AP_AI_MAX_TOKENS",
            "AP_AI_CODEGEN_MAX_TOKENS",
            "AP_AI_TEMPERATURE",
            "AP_AI_REASONING_EFFORT",
            "AP_AI_DEEPSEEK_THINKING",
            "AP_AI_DEEPSEEK_REASONING_EFFORT",
            "AP_AI_CHAT_MAX_ATTEMPTS",
            "AP_AI_CODEGEN_MAX_ATTEMPTS",
            "AP_AI_DAILY_TOKEN_BUDGET",
            "AP_AI_PROJECT_DAILY_TOKEN_BUDGET",
            "AP_AI_ORG_DAILY_TOKEN_BUDGET",
            "AP_AI_ENFORCE_TOKEN_BUDGET",
        ],
    },
    {
        "id": "vector_rag",
        "title": "向量 / RAG",
        "keys": [
            "AP_AI_EMBEDDING_MODEL",
            "AP_RAG_EMBEDDER",
            "AP_RAG_TOP_K",
            "AP_RAG_SCORE_THRESHOLD",
            "AP_RAG_HYBRID",
            "AP_RAG_FTS_FACTOR",
            "AP_RAG_FTS_MAX_CANDIDATES",
            "AP_ENABLE_CASE_GENERATION_RAG",
        ],
    },
    {
        "id": "case_generation",
        "title": "用例生成",
        "keys": [
            "AP_MAX_CASE_NUM",
            "AP_CONTENT_SIMILARITY_THRESHOLD",
            "AP_ENABLE_CONTENT_DEDUP",
            "AP_CONTENT_DEDUP_BATCH_SIZE",
            "AP_ENABLE_EXPERIMENTAL_ACTIONS",
        ],
    },
    {
        "id": "performance",
        "title": "性能",
        "keys": [
            "AP_CHUNK_SIZE",
            "AP_MAX_WORKERS",
            "AP_ENABLE_PARALLEL_PROCESSING",
            "AP_ENABLE_STREAMING",
        ],
    },
    {
        "id": "file_processing",
        "title": "文件处理",
        "keys": ["AP_MAX_MEMORY_MB"],
    },
)

# 设计配置基础校验规则：key -> (kind, min, max)
_DESIGN_VALIDATE: dict[str, tuple[str, float | None, float | None]] = {
    "AP_MAX_CASE_NUM": ("int", 1, 100),
    "AP_CONTENT_SIMILARITY_THRESHOLD": ("float", 0.0, 1.0),
    "AP_CONTENT_DEDUP_BATCH_SIZE": ("int", 1, 1000),
    "AP_CHUNK_SIZE": ("int", 100, 50000),
    "AP_MAX_WORKERS": ("int", 1, 32),
    "AP_MAX_MEMORY_MB": ("int", 64, 8192),
    "AP_RAG_TOP_K": ("int", 1, 50),
    "AP_RAG_SCORE_THRESHOLD": ("float", 0.0, 1.0),
    "AP_RAG_FTS_FACTOR": ("int", 5, 200),
    "AP_RAG_FTS_MAX_CANDIDATES": ("int", 50, 2000),
    "AP_AI_TIMEOUT_SEC": ("int", 5, 600),
    "AP_AI_MAX_TOKENS": ("int", 64, 128000),
    "AP_AI_CODEGEN_MAX_TOKENS": ("int", 512, 8192),
    "AP_AI_TEMPERATURE": ("float", 0.0, 2.0),
    "AP_AI_CHAT_MAX_ATTEMPTS": ("int", 1, 10),
    "AP_AI_CODEGEN_MAX_ATTEMPTS": ("int", 1, 4),
    "AP_AI_DAILY_TOKEN_BUDGET": ("int", 0, 1000000000),
    "AP_AI_PROJECT_DAILY_TOKEN_BUDGET": ("int", 0, 1000000000),
    "AP_AI_ORG_DAILY_TOKEN_BUDGET": ("int", 0, 1000000000),
}

# 落盘加密的键
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "MC_WEBHOOK_SECRET",
        "MC_ALERT_SECRET",
        "AP_AI_API_KEY",
    }
)

# GET 返回给前端时用占位符；PUT 收到该值则保持原密钥
SECRET_MASK = "********"


def runtime_config_path() -> Path:
    raw = os.environ.get("MC_RUNTIME_CONFIG", "").strip()
    if raw:
        return Path(raw)
    return data_dir() / "mc_runtime_config.json"


def has_secure_config_secret_material() -> bool:
    """是否具备可用于落盘加密的非开发默认材料。"""
    if os.environ.get("MC_CONFIG_SECRET", "").strip():
        return True
    jwt = os.environ.get("MC_JWT_SECRET", "").strip()
    return bool(jwt) and jwt != _INSECURE_DEV_JWT_SECRET


def _config_secret_material(*, allow_insecure_legacy: bool = False) -> bytes:
    """解析 at-rest 加密主密钥材料。

    - 正常加密/解密：``MC_CONFIG_SECRET`` → 非默认 ``MC_JWT_SECRET``（fail closed）。
    - ``allow_insecure_legacy=True``：**仅**使用历史开发默认 JWT 材料，用于解密旧密文
      （不得再混入当前 MC_CONFIG_SECRET，否则迁移读路径会失败）。
    """
    if allow_insecure_legacy:
        return _INSECURE_DEV_JWT_SECRET.encode("utf-8")
    cfg = os.environ.get("MC_CONFIG_SECRET", "").strip()
    if cfg:
        return cfg.encode("utf-8")
    jwt = os.environ.get("MC_JWT_SECRET", "").strip()
    if jwt and jwt != _INSECURE_DEV_JWT_SECRET:
        return jwt.encode("utf-8")
    raise ValueError(
        "缺少安全加密材料：写入密钥类运维配置前请设置 MC_CONFIG_SECRET，"
        "或将 MC_JWT_SECRET 设为非开发默认值（不可使用 "
        f"{_INSECURE_DEV_JWT_SECRET!r}）"
    )


def _fernet(*, allow_insecure_legacy: bool = False):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"autopilot-mc-runtime-config-v1",
        info=b"ops-config",
    ).derive(_config_secret_material(allow_insecure_legacy=allow_insecure_legacy))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plain: str) -> str:
    text = plain if isinstance(plain, str) else str(plain)
    if not text:
        return ""
    if text.startswith(_ENC_PREFIX):
        return text
    # fail closed：禁止用已知开发默认密钥加密新密文
    token = _fernet(allow_insecure_legacy=False).encrypt(text.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def _decrypt_secret_with_meta(value: str) -> tuple[str, bool]:
    """返回 (明文, used_legacy_insecure_material)。"""
    from cryptography.fernet import InvalidToken

    text = value if isinstance(value, str) else str(value)
    if not text.startswith(_ENC_PREFIX):
        return text, False
    raw_token = text[len(_ENC_PREFIX) :].encode("ascii")
    _decrypt_errs = (InvalidToken, ValueError, TypeError, UnicodeDecodeError)
    if has_secure_config_secret_material():
        try:
            plain = _fernet(allow_insecure_legacy=False).decrypt(raw_token).decode("utf-8")
            return plain, False
        except _decrypt_errs:
            # 密钥材料不匹配时再试历史默认材料
            pass
    try:
        plain = _fernet(allow_insecure_legacy=True).decrypt(raw_token).decode("utf-8")
        return plain, True
    except _decrypt_errs as exc:
        logger.warning("runtime config decrypt failed: %s", exc)
        raise ValueError("failed to decrypt runtime config secret") from exc


def decrypt_secret(value: str) -> str:
    plain, _legacy = _decrypt_secret_with_meta(value)
    return plain


def _decode_loaded(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """解码磁盘 JSON；第二返回值表示是否需用安全材料重写落盘密文。

    触发升密（AUD-2026-05）：
    - legacy 弱材料密文；
    - 历史明文写入的 SECRET_KEYS（无 ``enc:v1:`` 前缀）。
    仅在 ``has_secure_config_secret_material()`` 为真时标记，避免无主密钥时反复告警。
    """
    out: dict[str, Any] = {}
    needs_reencrypt = False
    secure = has_secure_config_secret_material()
    for k, v in raw.items():
        key = str(k)
        if key not in EDITABLE_KEYS:
            continue
        if key in SECRET_KEYS and isinstance(v, str) and v.startswith(_ENC_PREFIX):
            plain, used_legacy = _decrypt_secret_with_meta(v)
            out[key] = plain
            if used_legacy and secure:
                needs_reencrypt = True
        elif key in SECRET_KEYS and isinstance(v, str) and v.strip():
            # 磁盘明文密钥：读入内存后，有安全材料则 rewrite 为 enc:v1:
            out[key] = v
            if secure:
                needs_reencrypt = True
        else:
            out[key] = v
    return out, needs_reencrypt


def _encode_for_disk(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = str(k)
        if key not in EDITABLE_KEYS:
            continue
        if key in SECRET_KEYS and v is not None and str(v) != "":
            out[key] = encrypt_secret(str(v))
        else:
            out[key] = v
    return out


def _load_unlocked() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    path = runtime_config_path()
    data: dict[str, Any] = {}
    needs_reencrypt = False
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data, needs_reencrypt = _decode_loaded(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime config load failed: %s", exc)
    if needs_reencrypt:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            disk = _encode_for_disk(data)
            path.write_text(
                json.dumps(disk, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "runtime config secrets re-encrypted with secure "
                "MC_CONFIG_SECRET/MC_JWT_SECRET (legacy ciphertext or plaintext upgrade)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime config re-encrypt skipped: %s", exc)
    _cache = data
    return data


def load_runtime_config() -> dict[str, Any]:
    with _lock:
        return dict(_load_unlocked())


def reload_runtime_config() -> dict[str, Any]:
    global _cache
    with _lock:
        _cache = None
        return dict(_load_unlocked())


def get_override(key: str) -> Any | None:
    with _lock:
        data = _load_unlocked()
        if key not in data:
            return None
        return data[key]


def save_runtime_config(updates: dict[str, Any], *, replace: bool = False) -> dict[str, Any]:
    """合并或替换可编辑键；值为 null 表示删除覆盖（回退环境变量）。

    密钥类字段以 enc:v1:… 写入磁盘；返回/缓存中为明文。
    GET 掩码 ``********`` 或空串表示「保持原密钥」，不写入覆盖。
    """
    global _cache
    _WEBHOOK_URL_KEYS = (
        "MC_WEBHOOK_URL",
        "MC_DESIGN_WEBHOOK_URL",
        "MC_ALERT_WEBHOOK_URL",
    )
    with _lock:
        cur = {} if replace else dict(_load_unlocked())
        for k, v in (updates or {}).items():
            key = str(k)
            if key not in EDITABLE_KEYS:
                continue
            if v is None:
                cur.pop(key, None)
                continue
            if key in SECRET_KEYS:
                raw = str(v)
                if raw == "" or raw == SECRET_MASK:
                    continue  # 保持现有覆盖 / 环境变量
            if key in _WEBHOOK_URL_KEYS:
                from autopilot_platform.core.webhook_security import validate_webhook_url

                # 空串表示清除；非空须过 SSRF 结构校验（不强制 DNS）
                v = validate_webhook_url(str(v or "").strip(), resolve=False)
            cur[key] = v
        path = runtime_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        disk = _encode_for_disk(cur)
        path.write_text(
            json.dumps(disk, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _cache = cur
        return dict(cur)


def cfg_str(key: str, env_default: str = "") -> str:
    """运行时覆盖优先，否则环境变量，否则 default。"""
    ov = get_override(key)
    if ov is not None:
        return str(ov).strip()
    return os.environ.get(key, env_default).strip()


def cfg_bool(key: str, env_default: str = "1") -> bool:
    raw = cfg_str(key, env_default).lower()
    return raw not in ("0", "false", "no", "off", "")


def cfg_int(key: str, env_default: str, *, minimum: int | None = None) -> int:
    raw = cfg_str(key, env_default) or env_default
    try:
        n = int(raw)
    except ValueError:
        n = int(env_default)
    if minimum is not None:
        n = max(minimum, n)
    return n


def cfg_float(
    key: str,
    env_default: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = cfg_str(key, env_default) or env_default
    try:
        n = float(raw)
    except ValueError:
        n = float(env_default)
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


# ---- 设计域性能/去重开关（运维配置真源） ----


def content_dedup_enabled() -> bool:
    return cfg_bool("AP_ENABLE_CONTENT_DEDUP", "1")


def content_similarity_threshold() -> float:
    return cfg_float("AP_CONTENT_SIMILARITY_THRESHOLD", "0.8", minimum=0.0, maximum=1.0)


def content_dedup_batch_size() -> int:
    return cfg_int("AP_CONTENT_DEDUP_BATCH_SIZE", "100", minimum=1)


def design_chunk_size() -> int:
    """文档启发式切分 / 单块正文上限（字符）。"""
    return cfg_int("AP_CHUNK_SIZE", "1000", minimum=100)


def design_max_workers() -> int:
    return cfg_int("AP_MAX_WORKERS", "3", minimum=1)


def parallel_processing_enabled() -> bool:
    return cfg_bool("AP_ENABLE_PARALLEL_PROCESSING", "0")


def streaming_enabled() -> bool:
    return cfg_bool("AP_ENABLE_STREAMING", "1")


def design_max_memory_mb() -> int:
    """设计文档上传内存上限（MB）。"""
    return cfg_int("AP_MAX_MEMORY_MB", "500", minimum=1)


def describe_config() -> dict[str, Any]:
    """供 GET /ops/config：effective + source（密钥字段掩码，不回传明文）。"""
    from ..ai import ai_config as ai_cfg
    from ..core import settings as mc_settings

    effective = {
        "MC_WEBHOOK_URL": mc_settings.webhook_url(),
        "MC_WEBHOOK_SECRET": mc_settings.webhook_secret(),
        "MC_DESIGN_WEBHOOK_URL": mc_settings.design_webhook_url(),
        "MC_DESIGN_WEBHOOK_USE_JOB_URL": (
            "1" if mc_settings.design_webhook_use_job_url() else "0"
        ),
        "MC_WEBHOOK_ALLOW_LOOPBACK": (
            "1" if cfg_bool("MC_WEBHOOK_ALLOW_LOOPBACK", "0") else "0"
        ),
        "MC_ALERT_WEBHOOK_URL": mc_settings.alert_webhook_url(),
        "MC_ALERT_CHANNEL": mc_settings.alert_channel(),
        "MC_ALERT_SECRET": mc_settings.alert_secret(),
        "MC_ALERT_ON_FAILED": "1" if mc_settings.alert_on_failed() else "0",
        "MC_ALERT_ON_STALE": "1" if mc_settings.alert_on_stale() else "0",
        "MC_ALERT_ON_RUNNER_OFFLINE": (
            "1" if mc_settings.alert_on_runner_offline() else "0"
        ),
        "MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC": str(
            mc_settings.alert_runner_offline_cooldown_sec()
        ),
        "MC_ALERT_ON_DEVICE_EMPTY": (
            "1" if mc_settings.alert_on_device_empty() else "0"
        ),
        "MC_JOB_STALE_SEC": str(mc_settings.job_stale_sec()),
        "MC_ARTIFACT_RETENTION_DAYS": str(mc_settings.artifact_retention_days()),
        "MC_APP_BUILD_RETENTION_DAYS": str(mc_settings.app_build_retention_days()),
        "MC_JOB_REPORT_RETENTION_DAYS": str(mc_settings.job_report_retention_days()),
        "MC_APP_BUILD_MAX_MB": str(mc_settings.app_build_max_mb()),
        "MC_APP_BUILD_MAX_COUNT": str(mc_settings.app_build_max_count_per_project()),
        "MC_APP_BUILD_MAX_TOTAL_MB": str(mc_settings.app_build_max_total_mb_per_project()),
        "MC_METRICS_ENABLED": "1" if mc_settings.metrics_enabled() else "0",
        "MC_REQUIRE_JOB_DEVICES": "1" if mc_settings.require_job_devices() else "0",
        "MC_REQUIRE_ARTIFACT_MANIFEST": (
            "1" if mc_settings.require_artifact_manifest() else "0"
        ),
        "MC_ENFORCE_RUNTIME_VERSION": (
            "1" if mc_settings.enforce_runtime_version() else "0"
        ),
        "AP_AI_PROVIDER": ai_cfg.ai_provider(),

        "AP_AI_API_KEY": ai_cfg.ai_api_key(),
        "AP_AI_BASE_URL": ai_cfg.ai_base_url(),
        "AP_AI_MODEL": ai_cfg.ai_model(),
        "AP_AI_PLANNING_MODEL": cfg_str("AP_AI_PLANNING_MODEL", ""),
        "AP_AI_LOCATE_MODEL": cfg_str("AP_AI_LOCATE_MODEL", ""),
        "AP_AI_TIMEOUT_SEC": str(int(ai_cfg.ai_timeout_sec())),
        "AP_AI_MAX_TOKENS": str(int(ai_cfg.ai_max_tokens())),
        "AP_AI_CODEGEN_MAX_TOKENS": str(int(ai_cfg.ai_codegen_max_tokens())),
        "AP_AI_TEMPERATURE": str(ai_cfg.ai_temperature()),
        "AP_AI_REASONING_EFFORT": ai_cfg.ai_reasoning_effort(),
        "AP_AI_DEEPSEEK_THINKING": cfg_str("AP_AI_DEEPSEEK_THINKING", ""),
        "AP_AI_DEEPSEEK_REASONING_EFFORT": ai_cfg.deepseek_reasoning_effort(),
        "AP_AI_CHAT_MAX_ATTEMPTS": str(int(ai_cfg.ai_chat_max_attempts())),
        "AP_AI_CODEGEN_MAX_ATTEMPTS": str(int(ai_cfg.ai_codegen_max_attempts())),
        "AP_AI_DAILY_TOKEN_BUDGET": cfg_str("AP_AI_DAILY_TOKEN_BUDGET", "0"),
        "AP_AI_PROJECT_DAILY_TOKEN_BUDGET": cfg_str(
            "AP_AI_PROJECT_DAILY_TOKEN_BUDGET", "0"
        ),
        "AP_AI_ORG_DAILY_TOKEN_BUDGET": cfg_str("AP_AI_ORG_DAILY_TOKEN_BUDGET", "0"),
        "AP_AI_ENFORCE_TOKEN_BUDGET": cfg_str("AP_AI_ENFORCE_TOKEN_BUDGET", "0"),
        "AP_AI_REJECT_DEGRADED": "1" if ai_cfg.ai_reject_degraded() else "0",
        "AP_AI_EMBEDDING_MODEL": ai_cfg.ai_embedding_model(),
        "AP_RAG_EMBEDDER": ai_cfg.rag_embedder(),
        "AP_RAG_TOP_K": cfg_str("AP_RAG_TOP_K", "5"),
        "AP_RAG_SCORE_THRESHOLD": cfg_str("AP_RAG_SCORE_THRESHOLD", "0.3"),
        "AP_RAG_HYBRID": cfg_str("AP_RAG_HYBRID", "1"),
        "AP_RAG_FTS_FACTOR": cfg_str("AP_RAG_FTS_FACTOR", "40"),
        "AP_RAG_FTS_MAX_CANDIDATES": cfg_str("AP_RAG_FTS_MAX_CANDIDATES", "800"),
        "AP_ENABLE_CASE_GENERATION_RAG": cfg_str("AP_ENABLE_CASE_GENERATION_RAG", "1"),
        "AP_MAX_CASE_NUM": cfg_str("AP_MAX_CASE_NUM", "50"),
        "AP_CONTENT_SIMILARITY_THRESHOLD": cfg_str("AP_CONTENT_SIMILARITY_THRESHOLD", "0.8"),
        "AP_ENABLE_CONTENT_DEDUP": cfg_str("AP_ENABLE_CONTENT_DEDUP", "1"),
        "AP_CONTENT_DEDUP_BATCH_SIZE": cfg_str("AP_CONTENT_DEDUP_BATCH_SIZE", "100"),
        "AP_CHUNK_SIZE": cfg_str("AP_CHUNK_SIZE", "1000"),
        "AP_MAX_WORKERS": cfg_str("AP_MAX_WORKERS", "3"),
        "AP_ENABLE_PARALLEL_PROCESSING": cfg_str("AP_ENABLE_PARALLEL_PROCESSING", "0"),
        "AP_ENABLE_STREAMING": cfg_str("AP_ENABLE_STREAMING", "1"),
        "AP_MAX_MEMORY_MB": cfg_str("AP_MAX_MEMORY_MB", "500"),
        "AP_ENABLE_EXPERIMENTAL_ACTIONS": cfg_str("AP_ENABLE_EXPERIMENTAL_ACTIONS", "0"),
    }
    overrides = load_runtime_config()
    sources = {
        k: ("runtime" if k in overrides else ("env" if os.environ.get(k) else "default"))
        for k in EDITABLE_KEYS
    }
    secret_configured = {
        k: bool((effective.get(k) or "").strip()) for k in sorted(SECRET_KEYS)
    }
    public_values = dict(effective)
    for k in SECRET_KEYS:
        public_values[k] = SECRET_MASK if secret_configured[k] else ""
    # 覆盖字典也不回传明文密钥
    public_overrides = {
        k: (SECRET_MASK if k in SECRET_KEYS and str(v or "").strip() else v)
        for k, v in overrides.items()
    }
    return {
        "path": str(runtime_config_path()),
        "editable_keys": list(EDITABLE_KEYS),
        "ops_editable_keys": list(OPS_CONFIG_KEYS),
        "design_editable_keys": list(DESIGN_CONFIG_KEYS),
        "secret_keys": sorted(SECRET_KEYS),
        "secret_configured": secret_configured,
        "secret_mask": SECRET_MASK,
        "values": public_values,
        "overrides": public_overrides,
        "sources": sources,
        "secrets_encrypted_at_rest": True,
        "bootstrap": {
            "platform_base_url": mc_settings.platform_public_base_url(),
            "config_priority": "runtime_json > env > code_default",
            "bootstrap_keys": [
                "MC_HOST",
                "MC_PORT",
                "MC_PLATFORM_URL",
                "MC_SERVER",
                "MC_API_TOKEN",
                "MC_DATABASE_URL",
            ],
        },
        "design_ai_summary": {
            "provider": str(public_values.get("AP_AI_PROVIDER") or ""),
            "model": str(public_values.get("AP_AI_MODEL") or ""),
            "base_url": str(public_values.get("AP_AI_BASE_URL") or ""),
            "embedding_model": str(public_values.get("AP_AI_EMBEDDING_MODEL") or ""),
            "rag_embedder": str(public_values.get("AP_RAG_EMBEDDER") or ""),
            "api_key_configured": bool(secret_configured.get("AP_AI_API_KEY")),
        },
        "categories": [dict(c) for c in CONFIG_CATEGORIES],
        "note": (
            "运行时 JSON 覆盖优先于环境变量；密钥字段落盘加密（enc:v1）。"
            "GET 不回传密钥明文（********=已配置，保存时留空或占位符表示保持）。"
            "统一配置入口为「运维」配置中心（/ops/config 可写全部 EDITABLE_KEYS）；"
            "GET /design/config 设计用户可读设计域子集；PUT/import 仅 ops_admin（与运维密钥入口对齐）。"
            "Token/JWT/DB/SSO 证书等仍只读环境变量。密钥落盘须 MC_CONFIG_SECRET 或非默认 MC_JWT_SECRET；"
            "禁止用开发默认 JWT 加密新密钥。"
        ),
    }


def validate_design_config_values(values: dict[str, Any]) -> list[str]:
    """校验设计域配置值；返回错误列表（空=通过）。"""
    errors: list[str] = []
    for key, raw in (values or {}).items():
        k = str(key)
        if k not in DESIGN_CONFIG_KEYS:
            errors.append(f"不允许的配置键: {k}")
            continue
        if k in SECRET_KEYS:
            continue
        rule = _DESIGN_VALIDATE.get(k)
        if not rule:
            # bool-ish / free-form
            if k.startswith("AP_ENABLE_") or k.endswith("_THINKING"):
                s = str(raw).strip().lower()
                if s and s not in {"0", "1", "true", "false", "yes", "no", "on", "off"}:
                    errors.append(f"{k}: 应为布尔值")
            continue
        kind, lo, hi = rule
        try:
            if kind == "int":
                n = int(str(raw).strip())
            else:
                n = float(str(raw).strip())
        except (TypeError, ValueError):
            errors.append(f"{k}: 需要{'整数' if kind == 'int' else '数字'}")
            continue
        if lo is not None and n < lo:
            errors.append(f"{k}: 不能小于 {lo}")
        if hi is not None and n > hi:
            errors.append(f"{k}: 不能大于 {hi}")
    return errors


def export_design_config_payload() -> dict[str, Any]:
    """导出设计域配置（密钥掩码），供备份/迁移。"""
    full = describe_config()
    values = {k: full["values"].get(k, "") for k in DESIGN_CONFIG_KEYS}
    return {
        "format": "autopilot-design-config",
        "version": 1,
        "keys": list(DESIGN_CONFIG_KEYS),
        "values": values,
        "categories": [dict(c) for c in DESIGN_CONFIG_CATEGORIES],
    }


def import_design_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """导入设计域配置；仅接受 DESIGN_CONFIG_KEYS，校验后落盘。"""
    if not isinstance(payload, dict):
        raise ValueError("配置内容必须是 JSON 对象")
    raw = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    if not isinstance(raw, dict):
        raise ValueError("缺少 values 对象")
    filtered = {str(k): v for k, v in raw.items() if str(k) in DESIGN_CONFIG_KEYS}
    if not filtered:
        raise ValueError("没有可导入的设计配置键")
    errs = validate_design_config_values(filtered)
    if errs:
        raise ValueError("; ".join(errs))
    save_runtime_config(filtered, replace=False)
    return export_design_config_payload()


def export_runtime_config_payload() -> dict[str, Any]:
    """导出全部可写配置（密钥掩码），供运维配置中心备份。"""
    full = describe_config()
    values = {k: full["values"].get(k, "") for k in EDITABLE_KEYS}
    return {
        "format": "autopilot-runtime-config",
        "version": 1,
        "keys": list(EDITABLE_KEYS),
        "values": values,
        "categories": [dict(c) for c in CONFIG_CATEGORIES],
    }


def import_runtime_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """导入全部或子集可写配置；兼容 autopilot-design-config。"""
    if not isinstance(payload, dict):
        raise ValueError("配置内容必须是 JSON 对象")
    raw = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    if not isinstance(raw, dict):
        raise ValueError("缺少 values 对象")
    filtered = {str(k): v for k, v in raw.items() if str(k) in EDITABLE_KEYS}
    if not filtered:
        raise ValueError("没有可导入的配置键")
    design_subset = {k: v for k, v in filtered.items() if k in DESIGN_CONFIG_KEYS}
    if design_subset:
        errs = validate_design_config_values(design_subset)
        if errs:
            raise ValueError("; ".join(errs))
    save_runtime_config(filtered, replace=False)
    return export_runtime_config_payload()
