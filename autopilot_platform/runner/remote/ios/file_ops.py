"""iOS AFC / App Documents 文件操作（go-ios fsync）。"""

from __future__ import annotations

import asyncio
import base64
import inspect
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios
from autopilot_platform.ap.runtime.subproc import run as hidden_run

ReplyFn = Callable[[dict[str, Any]], None]
_guard = threading.RLock()
_uploads: dict[str, tuple[Any, str, str, str, int, int]] = {}


def afc_src_candidates(path: str, app: str = "") -> list[str]:
    """go-ios AFC Stat 对无前导 ``/`` 的路径常报 error code 8（OBJECT_NOT_FOUND）。

    媒体根与 Flask 一致：``DCIM/...`` 与 ``/DCIM/...`` 都试。
    ``--app`` 沙箱必须从 ``/Documents`` 起（go-ios house_arrest VendDocuments）。
    """
    raw = (path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw in {".", "/"}:
        return ["/Documents"] if app else ["/"]
    out: list[str] = []

    def add(item: str) -> None:
        text = (item or "").strip()
        if text and text not in out:
            out.append(text)

    add(raw)
    if raw.startswith("/"):
        add(raw.lstrip("/") or "/")
    else:
        add("/" + raw)
    if app:
        rest = raw[len("/Documents") :] if raw.startswith("/Documents") else raw
        if rest.startswith("Documents"):
            rest = rest[len("Documents") :]
        rest = rest.lstrip("/")
        add("/Documents" + (f"/{rest}" if rest else ""))
        add("Documents" + (f"/{rest}" if rest else ""))
    return out


def _run(udid: str, args: list[str], timeout: int = 300) -> str:
    executable = resolve_go_ios()
    if executable is None:
        raise RuntimeError("未找到 go-ios，无法执行 iOS 文件操作")
    completed = hidden_run(
        [str(executable), "--udid", udid, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(output or f"go-ios exit {completed.returncode}")
    return output


def _fsync(app: str) -> list[str]:
    return ["fsync", *([f"--app={app}"] if app else [])]


def tree(udid: str, path: str = ".", app: str = "") -> dict[str, Any]:
    candidates = afc_src_candidates(path, app)
    last_error = ""
    for candidate in candidates:
        try:
            output = _run(udid, [*_fsync(app), "tree", f"--path={candidate}"], 60)
            return {"ok": True, "path": path, "app": app or None, "tree": output}
        except RuntimeError as exc:
            last_error = str(exc)
            if "error code: 8" not in last_error.lower() and "object not found" not in last_error.lower():
                raise
    raise RuntimeError(last_error or f"fsync tree 失败：{candidates[0] if candidates else path}")


def mkdir(udid: str, path: str, app: str = "") -> dict[str, Any]:
    target = (path or "").strip()
    if not target or target in {".", "/"}:
        raise ValueError("无效目录路径")
    _run(udid, [*_fsync(app), "mkdir", f"--path={target}"], 60)
    return {"ok": True, "path": target, "app": app or None}


def delete(udid: str, path: str, *, recursive: bool = False, app: str = "") -> dict[str, Any]:
    target = (path or "").strip()
    if not target or target in {".", "/"}:
        raise ValueError("不能删除根路径")
    args = [*_fsync(app), "rm"]
    if recursive:
        args.append("--r")
    args.append(f"--path={target}")
    _run(udid, args, 120)
    return {"ok": True, "path": target, "app": app or None}


_RENAME_MAX_BYTES = 32 * 1024 * 1024


def _pull_bytes(udid: str, path: str, app: str = "") -> bytes:
    chunks = pull(udid, path, app)
    data = b"".join(base64.b64decode(chunk) for chunk in chunks)
    if len(data) > _RENAME_MAX_BYTES:
        raise ValueError(
            f"文件超过 iOS 重命名上限 {_RENAME_MAX_BYTES} bytes，请先下载再上传"
        )
    return data


def rename(udid: str, src: str, dst: str, app: str = "") -> dict[str, Any]:
    source = (src or "").strip()
    target = (dst or "").strip()
    if not source or not target:
        raise ValueError("rename 缺少 src/dst")
    if source.endswith("/") or target.endswith("/"):
        raise ValueError("iOS 暂不支持目录重命名")
    payload = _pull_bytes(udid, source, app)
    with tempfile.NamedTemporaryFile(
        prefix="autopilot_ios_rename_",
        suffix=Path(source).suffix,
        delete=False,
        mode="wb",
    ) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name
    try:
        _run(
            udid,
            [
                *_fsync(app),
                "push",
                f"--srcPath={tmp_path}",
                f"--dstPath={target}",
            ],
            300,
        )
        _run(udid, [*_fsync(app), "rm", f"--path={source}"], 60)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return {"ok": True, "path": target, "src": source, "app": app or None}


def _pulled_file(temp_dir: str, src_path: str) -> Path:
    name = os.path.basename(src_path.rstrip("/")) or "download"
    local = Path(temp_dir) / name
    if local.is_file():
        return local
    found = [item for item in Path(temp_dir).rglob("*") if item.is_file()]
    if len(found) == 1:
        return found[0]
    raise FileNotFoundError(src_path)


def _chunk_bytes(data: bytes) -> list[str]:
    size = 48 * 1024
    if not data:
        return [""]
    return [
        base64.b64encode(data[offset : offset + size]).decode("ascii")
        for offset in range(0, len(data), size)
    ]


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _to_afc_bytes(payload: Any) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, memoryview):
        return payload.tobytes()
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    raise TypeError(f"AFC 内容类型无法读取：{type(payload)!r}")


def _open_afc_service(lockdown: Any, app: str) -> Any:
    """用 getattr 避开 pymobiledevice3 构造函数桩与实际签名不一致。"""
    if app:
        from pymobiledevice3.services import house_arrest

        cls = getattr(house_arrest, "HouseArrestService")
        try:
            return cls(lockdown, str(app), True)
        except TypeError:
            return cls(lockdown, str(app))
    from pymobiledevice3.services import afc

    return getattr(afc, "AfcService")(lockdown)


async def _afc_read_from_lockdown(lockdown: Any, path: str, app: str) -> bytes:
    service = _open_afc_service(lockdown, app)
    last_error: BaseException | None = None
    try:
        for candidate in afc_src_candidates(path, app):
            try:
                getter = getattr(service, "get_file_contents")
                payload = await _await_maybe(getter(candidate))
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            data = _to_afc_bytes(payload)
            if data:
                return data
            last_error = RuntimeError(f"empty file: {candidate}")
        raise RuntimeError(str(last_error) if last_error else f"afc missing {path}")
    finally:
        closer = getattr(service, "close", None)
        if callable(closer):
            closer()


def _pull_via_pmd3(udid: str, path: str, app: str = "") -> bytes:
    """Windows 上 go-ios 常把 AFC 路径 Clean 成反斜杠，Stat 报 error 8；改走 pymobiledevice3。"""
    from pymobiledevice3.lockdown import create_using_usbmux

    async def _read() -> bytes:
        created = await _await_maybe(create_using_usbmux(serial=udid or None))
        if hasattr(created, "__aenter__"):
            async with created as lockdown:
                return await _afc_read_from_lockdown(lockdown, path, app)
        return await _afc_read_from_lockdown(created, path, app)

    return asyncio.run(_read())


def pull(udid: str, path: str, app: str = "") -> list[str]:
    last_error = ""
    data = b""
    with tempfile.TemporaryDirectory(prefix="autopilot_ios_pull_") as temp_dir:
        for index, candidate in enumerate(afc_src_candidates(path, app)):
            attempt = Path(temp_dir) / str(index)
            attempt.mkdir()
            try:
                _run(
                    udid,
                    [
                        *_fsync(app),
                        "pull",
                        f"--srcPath={candidate}",
                        f"--dstPath={str(attempt)}",
                    ],
                )
                data = _pulled_file(str(attempt), candidate).read_bytes()
                break
            except (RuntimeError, FileNotFoundError) as exc:
                last_error = str(exc)
                continue
        else:
            try:
                data = _pull_via_pmd3(udid, path, app)
            except Exception as exc:  # noqa: BLE001
                hint = last_error or str(exc)
                raise RuntimeError(
                    f"iOS 拉取失败（AFC）：{hint}。若是相册图，可能尚未本机下载（iCloud 占位）。"
                ) from exc
    if not data:
        raise RuntimeError(
            f"iOS 拉取失败（AFC）：{last_error or path}。若是相册图，可能尚未本机下载（iCloud 占位）。"
        )
    return _chunk_bytes(data)


def begin_upload(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    name = os.path.basename(str(event.get("name") or ""))
    if not transfer_id or not name:
        raise ValueError("file.push 缺少 id/name")
    size = int(event.get("size") or 0)
    if size < 0 or size > 1024 * 1024 * 1024:
        raise ValueError("文件大小超过远控传输上限")
    tmp = tempfile.NamedTemporaryFile(
        prefix="autopilot_ios_push_",
        suffix=Path(name).suffix,
        delete=False,
        mode="wb",
    )
    with _guard:
        _uploads[transfer_id] = (
            tmp,
            str(event.get("remote") or name),
            str(event.get("app") or ""),
            tmp.name,
            0,
            size,
        )
    reply({"t": "file.ready", "id": transfer_id})


def upload_chunk(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _uploads.get(transfer_id)
        if state is None:
            raise LookupError("未知 transfer")
        tmp, remote, app, local, sequence, total = state
        got_sequence = int(event.get("seq", -1))
        if got_sequence != sequence:
            raise ValueError(f"分块乱序 seq={got_sequence}, expected={sequence}")
        data = base64.b64decode(str(event.get("data") or ""), validate=False)
        tmp.write(data)
        tmp.flush()
        received = int(tmp.tell())
        if total and received > total:
            raise ValueError("收到的数据超过声明大小")
        _uploads[transfer_id] = (
            tmp,
            remote,
            app,
            local,
            sequence + 1,
            total,
        )
    reply(
        {
            "t": "file.progress",
            "id": transfer_id,
            "received": received,
            "total": total,
        }
    )


def end_upload(udid: str, event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _uploads.pop(transfer_id, None)
    if state is None:
        raise LookupError("未知 transfer")
    tmp, remote, app, local, _sequence, total = state
    tmp.close()
    try:
        if total and os.path.getsize(local) != total:
            raise ValueError("文件不完整")
        _run(
            udid,
            [
                *_fsync(app),
                "push",
                f"--srcPath={local}",
                f"--dstPath={remote}",
            ],
            600,
        )
        reply(
            {
                "t": "file.done",
                "id": transfer_id,
                "action": "push",
                "remote_path": remote,
            }
        )
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        reply(
            {
                "t": "file.error",
                "id": transfer_id,
                "error_code": "io_error",
                "error": str(exc),
            }
        )
    finally:
        try:
            os.unlink(local)
        except OSError:
            pass


def cancel_upload(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _uploads.pop(transfer_id, None)
    if state is not None:
        tmp, _remote, _app, local, _sequence, _total = state
        tmp.close()
        try:
            os.unlink(local)
        except OSError:
            pass
    reply({"t": "file.cancelled", "id": transfer_id})
