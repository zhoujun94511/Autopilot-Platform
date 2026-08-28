"""iOS 远控可靠命令分发（WebSocket/HTTP command channel）。"""

from __future__ import annotations

from typing import Any, Callable

from . import accessibility, app_ops, control_ops, device_info, file_ops
from .input_dispatch import press_wda_button

ReplyFn = Callable[[dict[str, Any]], None]


def dispatch(
    wda: Any,
    udid: str,
    event: dict[str, Any],
    reply: ReplyFn,
    stream_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> None:
    command = str(event.get("t") or event.get("name") or "")
    request_id = str(event.get("request_id") or "")

    def respond(payload: dict[str, Any]) -> None:
        if request_id:
            payload.setdefault("request_id", request_id)
        reply(payload)

    try:
        if command == "clipboard.get":
            respond({"t": "clipboard.value", "text": wda.get_pasteboard()})
        elif command == "clipboard.set":
            wda.set_pasteboard(str(event.get("text") or ""))
            respond({"t": "clipboard.ack", "ok": True})
        elif command in (
            "home",
            "lock",
            "unlock",
            "press_button",
            "volumeup",
            "volumedown",
        ):
            # 对齐 Flask IOSControlService.button：离散按键，失败只回 error，不拆会话。
            name = (
                str(event.get("name") or "")
                if command == "press_button"
                else command
            )
            press_wda_button(wda, name)
            print(
                f"[runner] remote ios button {name or command} ok",
                flush=True,
            )
            respond({"t": "button.ack", "button": name or command, "ok": True})
        elif command == "accessibility":
            respond(
                {
                    "t": "accessibility.result",
                    **accessibility.run(
                        udid,
                        str(event.get("feature") or ""),
                        str(event.get("action") or "toggle"),
                    ),
                }
            )
        elif command == "alert.get":
            respond({"t": "alert.result", **control_ops.get_alert(wda)})
        elif command == "alert.accept":
            respond(
                {
                    "t": "alert.ack",
                    **control_ops.alert_action(wda, "accept"),
                }
            )
        elif command == "alert.dismiss":
            respond(
                {
                    "t": "alert.ack",
                    **control_ops.alert_action(wda, "dismiss"),
                }
            )
        elif command == "input.text":
            respond(
                {
                    "t": "input.ack",
                    **control_ops.input_text(wda, str(event.get("text") or "")),
                }
            )
        elif command == "input.key":
            respond(
                {
                    "t": "input.ack",
                    **control_ops.input_key(wda, str(event.get("key") or event.get("name") or "")),
                }
            )
        elif command == "device.screenshot":
            respond(
                {
                    "t": "device.screenshot.result",
                    **control_ops.screenshot(wda),
                }
            )
        elif command == "file.list":
            respond(
                {
                    "t": "file.list.result",
                    **file_ops.tree(
                        udid,
                        str(event.get("path") or "."),
                        str(event.get("app") or ""),
                    ),
                }
            )
        elif command == "file.pull":
            chunks = file_ops.pull(
                udid,
                str(event.get("path") or ""),
                str(event.get("app") or ""),
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
        elif command == "file.push":
            file_ops.begin_upload(event, respond)
        elif command == "file.chunk":
            file_ops.upload_chunk(event, respond)
        elif command == "file.end":
            file_ops.end_upload(udid, event, respond)
        elif command == "file.cancel":
            file_ops.cancel_upload(event, respond)
        elif command == "file.mkdir":
            respond(
                {
                    "t": "file.mkdir.result",
                    **file_ops.mkdir(
                        udid,
                        str(event.get("path") or ""),
                        str(event.get("app") or ""),
                    ),
                }
            )
        elif command == "file.delete":
            respond(
                {
                    "t": "file.delete.result",
                    **file_ops.delete(
                        udid,
                        str(event.get("path") or ""),
                        recursive=bool(event.get("recursive")),
                        app=str(event.get("app") or ""),
                    ),
                }
            )
        elif command == "file.rename":
            respond(
                {
                    "t": "file.rename.result",
                    **file_ops.rename(
                        udid,
                        str(event.get("src") or ""),
                        str(event.get("dst") or ""),
                        str(event.get("app") or ""),
                    ),
                }
            )
        elif command == "device.info":
            respond(
                {
                    "t": "device.info.result",
                    **device_info.collect(udid, wda),
                }
            )
        elif command == "app.list":
            respond(
                {
                    "t": "app.list.result",
                    **app_ops.list_apps(
                        udid,
                        bool(event.get("system")),
                        filesharing=bool(event.get("filesharing")),
                    ),
                }
            )
        elif command == "app.uninstall":
            respond(
                {
                    "t": "app.uninstall.result",
                    **app_ops.uninstall(
                        udid, str(event.get("package") or "")
                    ),
                }
            )
        elif command == "app.launch":
            respond(
                {
                    "t": "app.launch.result",
                    **app_ops.launch(
                        wda, str(event.get("package") or "")
                    ),
                }
            )
        elif command == "app.stop":
            respond(
                {
                    "t": "app.stop.result",
                    **app_ops.stop(
                        wda, str(event.get("package") or "")
                    ),
                }
            )
        elif command == "app.install.begin":
            app_ops.begin_install(event, respond)
        elif command == "app.install.chunk":
            app_ops.install_chunk(event, respond)
        elif command == "app.install.end":
            app_ops.end_install(udid, event, respond)
        elif command == "app.install.cancel":
            app_ops.cancel_install(event, respond)
        elif command == "app.export":
            respond(
                {
                    "t": "app.export.error",
                    "error_code": "not_supported",
                    "error": "iOS 不允许从非越狱设备导出已安装 IPA",
                }
            )
        elif command.startswith("stream.") and stream_handler is not None:
            respond(
                {
                    "t": f"{command}.result",
                    **stream_handler(event),
                }
            )
        else:
            respond(
                {
                    "t": "error",
                    "for": command,
                    "error_code": "not_supported",
                    "error": f"不支持的 iOS 命令：{command}",
                }
            )
    except PermissionError as exc:
        respond(
            {
                "t": "error",
                "for": command,
                "error_code": "forbidden",
                "error": str(exc),
            }
        )
    except Exception as exc:  # noqa: BLE001
        respond(
            {
                "t": "error",
                "for": command,
                "error_code": "io_error",
                "error": str(exc),
            }
        )
