"""统一日志骨干（不依赖 PyQt，headless / CI 同样可用）。

设计要点：
- 所有模块用 `get_logger("xxx")` 取 `autopilot.xxx` 子 logger；根 logger 名为 `autopilot`。
- `setup_logging()` 幂等装配根 logger 的「轮转文件」+「stderr」handler，返回当日日志文件路径。
  落盘失败（只读盘/无权限）不致命：返回空串、仅保留 stderr。
- `run_log(name)` 上下文管理器：为单次运行额外挂一个按 run 命名的文件 handler，结束自动卸载。
- GUI 桥接 handler 由 `ui/log_bridge.QtConsoleHandler` 提供，通过 `attach_handler()` 挂上，
  两层解耦——日志层不 import 任何 PyQt。
- 记录可带 `extra={"ap_no_gui": True}`：表示「GUI 已自行渲染该信息」，桥接 handler 会跳过它，
  避免控制台重复出现（文件 handler 不受影响，照常落盘）。
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Iterator, Optional

ROOT = "autopilot"
_LOGFILE = ""
_configured = False
# 终端 / 文件 / GUI 控制台统一时间格式
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LINE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def get_logger(name: str = ROOT) -> logging.Logger:
    """取 autopilot.<name> 子 logger（传入已带 autopilot 前缀则原样用）。"""
    if name == ROOT or name.startswith(ROOT + "."):
        full = name
    else:
        full = f"{ROOT}.{name}"
    return logging.getLogger(full)


def _is_packaged() -> bool:
    """是否处于打包运行态（PyInstaller / cx_Freeze / py2app 等）。"""
    if getattr(sys, "frozen", False):
        return True
    if getattr(sys, "_MEIPASS", None):
        return True
    exe = (sys.executable or "").replace("\\", "/")
    return ".app/Contents/MacOS/" in exe


def log_dir() -> str:
    """应用日志目录。

    优先级：``AUTOPILOT_LOG_DIR`` → 打包态 ``~/.autopilot/logs`` → 开发态 ``<cwd>/logs``。
    打包后不能依赖 cwd（Windows 快捷方式 / macOS .app 的 cwd 常不可写或不稳定）。
    """
    override = (os.environ.get("AUTOPILOT_LOG_DIR") or "").strip()
    if override:
        return override
    if _is_packaged():
        return os.path.join(os.path.expanduser("~"), ".autopilot", "logs")
    return os.path.join(os.getcwd(), "logs")


def current_logfile() -> str:
    """当前（当日）主日志文件路径；未配置或落盘失败为空串。"""
    return _LOGFILE


def _formatter() -> logging.Formatter:
    return logging.Formatter(LOG_LINE_FORMAT, LOG_TIME_FORMAT)


def setup_logging(level: int = logging.INFO, directory: Optional[str] = None,
                  console: bool = True) -> str:
    """幂等装配根 logger。返回当日日志文件路径（落盘失败返回 ''）。"""
    global _LOGFILE, _configured
    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG)            # 由各 handler 自行过滤级别
    root.propagate = False                  # 不冒泡到 Python 根 logger（避免重复打印）
    if _configured:
        return _LOGFILE
    directory = directory or log_dir()
    # noinspection PyBroadException
    try:
        os.makedirs(directory, exist_ok=True)
        _LOGFILE = os.path.join(directory, f"autopilot_{datetime.now():%Y%m%d}.log")
        fh = RotatingFileHandler(_LOGFILE, maxBytes=5_000_000, backupCount=7,
                                 encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_formatter())
        root.addHandler(fh)
    except Exception:
        _LOGFILE = ""                        # 落盘失败不致命
    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(level)
        sh.setFormatter(_formatter())
        root.addHandler(sh)
    _configured = True
    return _LOGFILE


def attach_handler(handler: logging.Handler) -> None:
    """挂一个额外 handler 到根 logger（如 GUI 桥接 handler）。"""
    logging.getLogger(ROOT).addHandler(handler)


def detach_handler(handler: logging.Handler) -> None:
    logging.getLogger(ROOT).removeHandler(handler)


@contextmanager
def run_log(name: str, directory: Optional[str] = None) -> Iterator[str]:
    """为单次运行挂一个独立文件 handler；退出时移除并关闭。

    返回该 run 日志文件路径（落盘失败为 ''）。与主日志文件并存，便于「按次」回溯。"""
    root = logging.getLogger(ROOT)
    if not root.handlers:                    # 未 setup_logging（如纯单测）→ 不落盘、无害空转
        yield ""
        return
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))[:60] or "run"
    # noinspection PyBroadException
    try:
        d = os.path.join(directory or log_dir(), "runs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{datetime.now():%Y%m%d_%H%M%S}_{safe}.log")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_formatter())
        root.addHandler(fh)
    except Exception:
        path, fh = "", None
    try:
        yield path
    finally:
        if fh is not None:
            root.removeHandler(fh)
            # noinspection PyBroadException
            try:
                fh.close()
            except Exception:
                pass
