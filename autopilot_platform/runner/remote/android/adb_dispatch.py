"""Android 可靠 ``adb`` DataChannel 命令分发。"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from . import app_manager, device_info, file_browser, file_transfer

ReplyFn = Callable[[dict[str, Any]], None]


def dispatch(
    client: Any,
    message: str | bytes,
    reply: ReplyFn,
    *,
    device_id: str,
) -> None:
    try:
        event = json.loads(
            message
            if isinstance(message, str)
            else message.decode("utf-8", "ignore")
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return
    if not isinstance(event, dict):
        return
    event_type = str(event.get("t") or "")
    request_id = str(event.get("request_id") or "")

    def respond(payload: dict[str, Any]) -> None:
        if request_id:
            payload.setdefault("request_id", request_id)
        reply(payload)

    try:
        if event_type == "ping":
            respond({"t": "pong", "ts": time.time()})
        elif event_type == "clipboard.get":
            respond(
                {
                    "t": "clipboard.value",
                    "text": client.control.get_clipboard(),
                }
            )
        elif event_type == "clipboard.set":
            sequence = int(time.time_ns() & 0x7FFFFFFFFFFFFFFF)
            ok = client.control.set_clipboard(
                str(event.get("text") or ""),
                paste=bool(event.get("paste")),
                sequence=sequence,
            )
            respond(
                {
                    "t": "clipboard.ack",
                    "ok": bool(ok),
                    "sequence": sequence,
                }
            )
        elif event_type == "file.push":
            file_transfer.begin(event, respond)
        elif event_type == "file.chunk":
            file_transfer.chunk(event, respond)
        elif event_type == "file.end":
            try:
                from .app_manager import install_local_apk
            except ImportError:
                install_local_apk = None  # type: ignore[assignment]

            install = None
            if install_local_apk is not None:

                def install(path: str, force: bool) -> dict[str, Any]:
                    return install_local_apk(
                        device_id, path, force_replace=force
                    )

            file_transfer.end(
                event,
                client,
                respond,
                install_apk=install,
            )
        elif event_type == "file.cancel":
            file_transfer.cancel(event, respond)
        elif event_type == "device.info":
            respond(
                {
                    "t": "device.info.result",
                    **device_info.collect(device_id),
                }
            )
        elif event_type == "file.list":
            respond(
                {
                    "t": "file.list.result",
                    **file_browser.list_directory(
                        device_id,
                        str(event.get("path") or "/sdcard"),
                    ),
                }
            )
        elif event_type == "file.stat":
            respond(
                {
                    "t": "file.stat.result",
                    "entry": file_browser.stat_path(
                        device_id, str(event.get("path") or "")
                    ),
                }
            )
        elif event_type == "file.mkdir":
            respond(
                {
                    "t": "file.mkdir.result",
                    **file_browser.mkdir(
                        device_id, str(event.get("path") or "")
                    ),
                }
            )
        elif event_type == "file.rename":
            respond(
                {
                    "t": "file.rename.result",
                    **file_browser.rename(
                        device_id,
                        str(event.get("src") or ""),
                        str(event.get("dst") or ""),
                    ),
                }
            )
        elif event_type == "file.delete":
            respond(
                {
                    "t": "file.delete.result",
                    **file_browser.delete(
                        device_id,
                        str(event.get("path") or ""),
                        bool(event.get("recursive")),
                    ),
                }
            )
        elif event_type == "file.pull":
            chunks = file_browser.pull_chunks(
                device_id,
                str(event.get("path") or ""),
            )
            transfer_id = str(event.get("id") or request_id)
            respond(
                {
                    "t": "file.pull.ready",
                    "id": transfer_id,
                    "chunks": len(chunks),
                }
            )
            for sequence, data in enumerate(chunks):
                respond(
                    {
                        "t": "file.pull.chunk",
                        "id": transfer_id,
                        "seq": sequence,
                        "data": data,
                    }
                )
            respond({"t": "file.pull.done", "id": transfer_id})
        elif event_type == "app.list":
            respond(
                {
                    "t": "app.list.result",
                    **app_manager.list_packages(
                        device_id,
                        str(event.get("scope") or "all"),
                    ),
                }
            )
        elif event_type == "app.info":
            respond(
                {
                    "t": "app.info.result",
                    **app_manager.package_info(
                        device_id,
                        str(event.get("package") or ""),
                    ),
                }
            )
        elif event_type == "app.uninstall":
            respond(
                {
                    "t": "app.uninstall.result",
                    **app_manager.uninstall(
                        device_id,
                        str(event.get("package") or ""),
                        bool(event.get("keep_data")),
                    ),
                }
            )
        elif event_type == "app.launch":
            respond(
                {
                    "t": "app.launch.result",
                    **app_manager.launch(
                        device_id, str(event.get("package") or "")
                    ),
                }
            )
        elif event_type == "app.stop":
            respond(
                {
                    "t": "app.stop.result",
                    **app_manager.stop(
                        device_id, str(event.get("package") or "")
                    ),
                }
            )
        elif event_type == "app.export":
            exported = app_manager.export_apk(
                device_id, str(event.get("package") or "")
            )
            chunks = list(exported.pop("chunks"))
            transfer_id = str(event.get("id") or request_id)
            respond(
                {
                    "t": "app.export.ready",
                    "id": transfer_id,
                    "chunks": len(chunks),
                    **exported,
                }
            )
            for sequence, data in enumerate(chunks):
                respond(
                    {
                        "t": "app.export.chunk",
                        "id": transfer_id,
                        "seq": sequence,
                        "data": data,
                    }
                )
            respond(
                {
                    "t": "app.export.done",
                    "id": transfer_id,
                    "filename": exported["filename"],
                }
            )
        elif event_type == "stream.configure":
            from ..shared.stream_limits import sanitize_android_stream_config
            from . import scrcpyclients
            from .webrtc.peer_manager import get_peer_manager

            config = sanitize_android_stream_config(event)
            new_client = (
                scrcpyclients.reconfigure(device_id, **config)
                if config
                else client
            )
            if new_client is None:
                raise RuntimeError("scrcpy 流参数更新失败")
            peers = get_peer_manager()
            if new_client is not client:
                peers.reattach_for_device(device_id, new_client)

            def apply_bitrate(target_bps: int) -> None:
                adaptive_client = scrcpyclients.reconfigure(
                    device_id, bitrate=target_bps
                )
                if adaptive_client is not None:
                    peers.reattach_for_device(device_id, adaptive_client)

            if event.get("adaptive") is not None:
                current_bitrate = int(
                    scrcpyclients.get_device_config(device_id)["bitrate"]
                )
                peers.set_adaptive(
                    device_id,
                    bool(event.get("adaptive")),
                    initial_bps=current_bitrate,
                    on_target_bps=apply_bitrate,
                )
            respond(
                {
                    "t": "stream.configure.result",
                    "ok": True,
                    "config": scrcpyclients.get_device_config(device_id),
                    "adaptive": bool(event.get("adaptive")),
                }
            )
        elif event_type == "stream.keyframe":
            client.control.reset_video()
            respond({"t": "stream.keyframe.result", "ok": True})
        elif event_type == "stream.stats":
            from . import scrcpyclients

            respond(
                {
                    "t": "stream.stats.result",
                    "config": scrcpyclients.get_device_config(device_id),
                    "resolution": list(client.resolution or (0, 0)),
                    "alive": bool(client.alive),
                }
            )
        else:
            respond(
                {
                    "t": "error",
                    "for": event_type,
                    "error_code": "not_supported",
                    "error": f"不支持的 adb 命令：{event_type}",
                }
            )
    except PermissionError as exc:
        respond(
            {
                "t": "error",
                "for": event_type,
                "error_code": "forbidden",
                "error": str(exc),
            }
        )
    except (OSError, RuntimeError, ValueError, LookupError, AttributeError) as exc:
        respond(
            {
                "t": "error",
                "for": event_type,
                "error_code": "io_error",
                "error": str(exc),
            }
        )
