"""iOS App 列表、安装、卸载、启动与终止。"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios

ReplyFn = Callable[[dict[str, Any]], None]
_guard = threading.RLock()
_installs: dict[str, tuple[Any, str, int, int]] = {}


def _run(udid: str, args: list[str], timeout: int = 300) -> str:
    executable = resolve_go_ios()
    if executable is None:
        raise RuntimeError("未找到 go-ios")
    completed = subprocess.run(
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


def list_apps(
    udid: str,
    system: bool = False,
    *,
    filesharing: bool = False,
) -> dict[str, Any]:
    args = ["apps"]
    if system:
        args.append("--system")
    if filesharing:
        args.append("--filesharing")
    args.append("--list")
    output = _run(udid, args, 60)
    apps: list[dict[str, Any]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("{"):
            continue
        parts = line.split()
        bundle_id = parts[0]
        if len(parts) >= 3:
            version, name = parts[-1], " ".join(parts[1:-1])
        elif len(parts) == 2:
            version, name = "", parts[1]
        else:
            version, name = "", bundle_id
        apps.append(
            {
                "package": bundle_id,
                "bundle_id": bundle_id,
                "name": name or bundle_id,
                "version_name": version,
                "system": system,
                "export_supported": False,
            }
        )
    return {"ok": True, "packages": apps, "count": len(apps)}


def uninstall(udid: str, bundle_id: str) -> dict[str, Any]:
    _run(udid, ["uninstall", bundle_id], 120)
    return {"ok": True, "action": "uninstall", "package": bundle_id}


def launch(wda: Any, bundle_id: str) -> dict[str, Any]:
    wda.launch_app(bundle_id)
    return {"ok": True, "action": "launch", "package": bundle_id}


def stop(wda: Any, bundle_id: str) -> dict[str, Any]:
    wda.terminate_app(bundle_id)
    return {"ok": True, "action": "stop", "package": bundle_id}


def begin_install(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    name = os.path.basename(str(event.get("name") or ""))
    total = int(event.get("size") or 0)
    if not transfer_id or not name.lower().endswith(".ipa"):
        raise ValueError("iOS 安装仅接受 IPA")
    tmp = tempfile.NamedTemporaryFile(
        prefix="autopilot_ios_install_",
        suffix=".ipa",
        delete=False,
        mode="wb",
    )
    with _guard:
        _installs[transfer_id] = (tmp, tmp.name, 0, total)
    reply({"t": "app.install.ready", "id": transfer_id})


def install_chunk(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _installs.get(transfer_id)
        if state is None:
            raise LookupError("未知 install transfer")
        tmp, path, sequence, total = state
        got = int(event.get("seq", -1))
        if got != sequence:
            raise ValueError(f"分块乱序 seq={got}, expected={sequence}")
        data = base64.b64decode(str(event.get("data") or ""), validate=False)
        tmp.write(data)
        tmp.flush()
        received = int(tmp.tell())
        _installs[transfer_id] = (tmp, path, sequence + 1, total)
    reply(
        {
            "t": "app.install.progress",
            "id": transfer_id,
            "received": received,
            "total": total,
        }
    )


def end_install(udid: str, event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _installs.pop(transfer_id, None)
    if state is None:
        raise LookupError("未知 install transfer")
    tmp, path, _sequence, total = state
    tmp.close()
    try:
        if total and Path(path).stat().st_size != total:
            raise ValueError("IPA 文件不完整")
        _run(udid, ["install", f"--path={path}"], 600)
        reply({"t": "app.install.done", "id": transfer_id, "ok": True})
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def cancel_install(event: dict[str, Any], reply: ReplyFn) -> None:
    transfer_id = str(event.get("id") or "")
    with _guard:
        state = _installs.pop(transfer_id, None)
    if state:
        tmp, path, _sequence, _total = state
        tmp.close()
        try:
            os.unlink(path)
        except OSError:
            pass
    reply({"t": "app.install.cancelled", "id": transfer_id})


def cleanup_pending_installs() -> None:
    """远控会话结束时清掉未完成的 IPA 分块临时文件。"""
    with _guard:
        pending = list(_installs.items())
        _installs.clear()
    for _transfer_id, state in pending:
        tmp, path, _sequence, _total = state
        try:
            tmp.close()
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
