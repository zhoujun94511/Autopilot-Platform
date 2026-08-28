"""子进程启动参数：Windows GUI 进程下不弹控制台窗口。

打包后的 IDE（以及 ``pythonw run.py``）没有父控制台，此时任何 ``subprocess``
都会为子进程新建一个 conhost 窗口，在屏幕左上角一闪而过。设备监控每 3s 跑一次
``adb devices``，闪现尤其明显。所有 spawn 点统一走这里补 ``CREATE_NO_WINDOW``。

用 ``python run.py`` 启动时子进程继承已有控制台，本来就不闪，因此该标志在开发态
不改变任何行为。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
# 这两个标志会自带控制台语义，与 CREATE_NO_WINDOW 互斥
_CONSOLE_FLAGS = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010) | getattr(
    subprocess, "DETACHED_PROCESS", 0x00000008
)


def hidden_kwargs(kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回补好 ``creationflags`` 的 kwargs 副本；非 Windows 原样返回。

    调用方已显式要求新建/脱离控制台时不覆盖其意图。
    """
    out = dict(kwargs or {})
    if sys.platform != "win32":
        return out
    flags = int(out.get("creationflags", 0) or 0)
    if flags & _CONSOLE_FLAGS:
        return out
    out["creationflags"] = flags | CREATE_NO_WINDOW
    return out


def run(cmd, **kwargs):
    """``subprocess.run``，Windows 下不弹控制台窗口。"""
    return subprocess.run(cmd, **hidden_kwargs(kwargs))


def popen(cmd, **kwargs):
    """``subprocess.Popen``，Windows 下不弹控制台窗口。"""
    return subprocess.Popen(cmd, **hidden_kwargs(kwargs))


def check_output(cmd, **kwargs):
    """``subprocess.check_output``，Windows 下不弹控制台窗口。"""
    return subprocess.check_output(cmd, **hidden_kwargs(kwargs))
