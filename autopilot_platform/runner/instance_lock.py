"""同机同 runner_id 跨进程独占锁（防心跳覆盖 / 双 claim）。

使用 OS 级文件锁（Windows ``msvcrt.locking`` / Unix ``fcntl.flock``），
进程异常退出时内核自动释放，无需 PID 轮询清理。
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional


class RunnerInstanceBusyError(RuntimeError):
    """同 runner_id 已有本机进程持有实例锁。"""


def default_lock_dir() -> Path:
    override = (os.environ.get("MC_RUNNER_LOCK_DIR") or "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return Path(base) / "AutoPilot" / "runner-locks"
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "autopilot" / "runner-locks"
    return Path.home() / ".cache" / "autopilot" / "runner-locks"


def lock_path_for(runner_id: str, *, lock_dir: str | Path | None = None) -> Path:
    rid = (runner_id or "").strip() or "default"
    safe = "".join(c if (c.isalnum() or c in "-._") else "_" for c in rid)[:80] or "runner"
    digest = hashlib.sha256(rid.encode("utf-8")).hexdigest()[:16]
    root = Path(lock_dir) if lock_dir is not None else default_lock_dir()
    return root / f"{safe}-{digest}.lock"


class RunnerInstanceLock:
    """持有期间保持文件描述符打开；``release`` 或进程退出时释放。"""

    def __init__(
        self,
        runner_id: str,
        *,
        lock_dir: str | Path | None = None,
    ) -> None:
        self.runner_id = (runner_id or "").strip() or "default"
        self.path = lock_path_for(self.runner_id, lock_dir=lock_dir)
        self._fh: Optional[BinaryIO] = None
        self._atexit_registered = False

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> None:
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            _ensure_lockable_byte(fh)
            _lock_fd(fh)
        except OSError as exc:
            holder = _read_holder_meta(fh)
            try:
                fh.close()
            except OSError:
                pass
            detail = ""
            if holder.get("pid"):
                detail = f"（占用进程 pid={holder.get('pid')}）"
            raise RunnerInstanceBusyError(
                f"本机已有 Runner 占用 runner_id={self.runner_id!r}{detail}；"
                f"请先停止旧进程或改用不同 --runner-id。锁文件: {self.path}"
            ) from exc

        try:
            _write_holder_meta(
                fh,
                {"runner_id": self.runner_id, "pid": os.getpid()},
            )
        except OSError:
            pass

        self._fh = fh
        if not self._atexit_registered:
            atexit.register(self.release)
            self._atexit_registered = True

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            _unlock_fd(fh)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass

    def __enter__(self) -> "RunnerInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def acquire_runner_instance_lock(
    runner_id: str,
    *,
    lock_dir: str | Path | None = None,
) -> RunnerInstanceLock:
    """获取锁；失败抛 ``RunnerInstanceBusyError``。"""
    lock = RunnerInstanceLock(runner_id, lock_dir=lock_dir)
    lock.acquire()
    return lock


def _ensure_lockable_byte(fh: BinaryIO) -> None:
    fh.seek(0, os.SEEK_END)
    if fh.tell() == 0:
        fh.write(b"\0")
        fh.flush()
    fh.seek(0)


def _lock_fd(fh: BinaryIO) -> None:
    fd = fh.fileno()
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fh: BinaryIO) -> None:
    fd = fh.fileno()
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _write_holder_meta(fh: BinaryIO, meta: dict) -> None:
    payload = json.dumps(meta, ensure_ascii=False).encode("utf-8") or b"{}"
    # 不 truncate(0)：Windows 字节锁绑定已存在区域，覆盖写入更稳妥
    fh.seek(0)
    fh.write(payload)
    fh.truncate(len(payload))
    fh.flush()


def _read_holder_meta(fh: BinaryIO) -> dict:
    try:
        fh.seek(0)
        raw = fh.read()
        if not raw or raw == b"\0":
            return {}
        data = json.loads(raw.decode("utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
