"""可靠 DataChannel 分块上传状态机。"""

from __future__ import annotations

import base64
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ReplyFn = Callable[[dict[str, Any]], None]
_STAGING_DIR = Path(tempfile.gettempdir()) / "autopilot-remote-uploads"
_MAX_TRANSFER_BYTES = 1024 * 1024 * 1024
_TRANSFER_TTL_SECONDS = 30 * 60


@dataclass(slots=True)
class FileTransfer:
    transfer_id: str
    name: str
    size: int
    remote: str
    received: int = 0
    sequence: int = 0
    created_at: float = field(default_factory=time.monotonic)
    local_path: str = ""
    _file: Any = None

    def __post_init__(self) -> None:
        if self.size < 0 or self.size > _MAX_TRANSFER_BYTES:
            raise ValueError("文件大小超过远控传输上限")
        self.name = os.path.basename(self.name)
        self.remote = self.remote or "/sdcard/Download/"
        _STAGING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            dir=_STAGING_DIR,
            suffix=Path(self.name).suffix,
            mode="wb",
        )
        self._file = tmp
        self.local_path = tmp.name

    def append(self, sequence: int, data: bytes) -> None:
        if sequence != self.sequence:
            raise ValueError(
                f"分块乱序 seq={sequence}, expected={self.sequence}"
            )
        if self.received + len(data) > self.size > 0:
            raise ValueError("收到的数据超过声明大小")
        self._file.write(data)
        self._file.flush()
        self.received += len(data)
        self.sequence += 1

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def cleanup(self) -> None:
        self.close()
        try:
            os.unlink(self.local_path)
        except OSError:
            pass


_guard = threading.RLock()
_transfers: dict[str, FileTransfer] = {}


def _prune() -> None:
    now = time.monotonic()
    expired = [
        key
        for key, item in _transfers.items()
        if now - item.created_at > _TRANSFER_TTL_SECONDS
    ]
    for key in expired:
        _transfers.pop(key).cleanup()


def begin(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    name = str(event.get("name") or "")
    if not transfer_id or not name:
        raise ValueError("file.push 缺少 id/name")
    with _guard:
        _prune()
        if transfer_id in _transfers:
            raise ValueError("重复 transfer id")
        transfer = FileTransfer(
            transfer_id=transfer_id,
            name=name,
            size=int(event.get("size") or 0),
            remote=str(event.get("remote") or "/sdcard/Download/"),
        )
        _transfers[transfer_id] = transfer
    reply({"t": "file.ready", "id": transfer_id})


def chunk(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        transfer = _transfers.get(transfer_id)
        if transfer is None:
            raise LookupError("未知 transfer")
        raw = base64.b64decode(str(event.get("data") or ""), validate=False)
        transfer.append(int(event.get("seq", -1)), raw)
        received, total = transfer.received, transfer.size
    reply(
        {
            "t": "file.progress",
            "id": transfer_id,
            "received": received,
            "total": total,
        }
    )


def end(
    event: dict[str, Any],
    client: Any,
    reply: ReplyFn,
    *,
    install_apk: Callable[[str, bool], dict[str, Any]] | None = None,
) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        transfer = _transfers.pop(transfer_id, None)
    if transfer is None:
        raise LookupError("未知 transfer")
    transfer.close()
    try:
        if transfer.size and transfer.received != transfer.size:
            raise ValueError(
                f"文件不完整 received={transfer.received}, expected={transfer.size}"
            )
        if (
            Path(transfer.name).suffix.lower() in {".apk", ".xapk"}
            and install_apk
            and bool(event.get("install"))
        ):
            result = install_apk(transfer.local_path, bool(event.get("force")))
            if not result.get("ok", False):
                reply({"t": "file.error", "id": transfer_id, **result})
            else:
                reply({"t": "file.done", "id": transfer_id, **result})
            return
        remote = transfer.remote
        if remote.endswith("/"):
            remote += transfer.name
        client.device.sync.push(transfer.local_path, remote)
        reply(
            {
                "t": "file.done",
                "id": transfer_id,
                "action": "push",
                "filename": transfer.name,
                "remote_path": remote,
            }
        )
    except (OSError, RuntimeError, ValueError, LookupError, AttributeError, PermissionError) as exc:
        reply(
            {
                "t": "file.error",
                "id": transfer_id,
                "error_code": "io_error",
                "error": str(exc),
            }
        )
    finally:
        transfer.cleanup()


def cancel(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        transfer = _transfers.pop(transfer_id, None)
    if transfer is not None:
        transfer.cleanup()
    reply({"t": "file.cancelled", "id": transfer_id})


def cleanup_all_transfers() -> None:
    """远控会话结束时清掉未完成上传的临时文件，避免占盘影响下次推送。"""
    with _guard:
        pending = list(_transfers.values())
        _transfers.clear()
    for transfer in pending:
        transfer.cleanup()
