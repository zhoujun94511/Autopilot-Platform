"""Platform 进程统一日志装配（轮转文件 + stderr）。

与 Runner/IDE 的 ``ap/runtime/log.py`` 分离：Platform 使用 ``autopilot_platform`` 命名空间，
落盘目录由 ``MC_PLATFORM_LOGS_DIR`` 控制（默认仓库根 ``logs/``）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .settings import log_format, log_level, platform_logs_root

ROOT_LOGGER = "autopilot_platform"
_LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_TEXT_LINE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_configured = False
_logfile = ""


def current_platform_logfile() -> str:
    """当前 Platform 主日志文件路径；未配置或落盘失败为空串。"""
    return _logfile


class _JsonLogFormatter(logging.Formatter):
    """``MC_LOG_FORMAT=json`` 时的单行 JSON 日志。"""

    def format(self, record: logging.LogRecord) -> str:
        from .request_context import get_request_id

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _line_formatter() -> logging.Formatter:
    if log_format() == "json":
        return _JsonLogFormatter()
    return logging.Formatter(_TEXT_LINE_FORMAT, _LOG_TIME_FORMAT)


def _prune_old_platform_logs(directory: Path, *, keep_days: int = 14) -> None:
    """清理超过保留天数的 platform_*.log* 历史日志文件。"""
    import time

    if keep_days <= 0:
        return
    cutoff = time.time() - keep_days * 86400
    for p in directory.glob("platform_*.log*"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except OSError:
            pass


def setup_platform_logging(*, force: bool = False) -> str:
    """装配根 logger；在进程启动或单元测试重建时调用。"""
    global _configured, _logfile

    if _configured and not force:
        return _logfile

    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(logging.DEBUG)
    root.propagate = False

    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except OSError:
                pass
        _configured = False
        _logfile = ""

    if _configured:
        return _logfile

    level = log_level()
    formatter = _line_formatter()
    stdout_only = os.environ.get("MC_LOG_TO_STDOUT_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    if not stdout_only:
        try:
            directory = platform_logs_root()
            keep_days = max(1, int(os.environ.get("MC_PLATFORM_LOG_RETENTION_DAYS", "14") or 14))
            _prune_old_platform_logs(directory, keep_days=keep_days)
            _logfile = str(directory / f"platform_{datetime.now():%Y%m%d}.log")
            fh = RotatingFileHandler(
                _logfile,
                maxBytes=5_000_000,
                backupCount=7,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except (OSError, ValueError):
            _logfile = ""

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(level)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    _configured = True
    return _logfile
