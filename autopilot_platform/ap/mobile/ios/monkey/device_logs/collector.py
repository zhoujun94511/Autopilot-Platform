"""Monkey 设备 syslog / crash 采集编排。

仅管理本模块启动的 syslog 子进程；**不** stop 隧道、runwda、WDA 会话或 mobile driver。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

from . import goios_backend, pmd3_backend
from .crash_diff import diff_new, is_relevant_crash, list_crash_files, parse_crash_ls

if TYPE_CHECKING:
    from .....keywords.context import ExecutionContext


@dataclass
class LogCollectionOptions:
    enabled: bool = True
    backend: str = "auto"
    syslog_enabled: bool = True
    crash_enabled: bool = True
    filter_bundle: bool = True
    syslog_max_bytes: int = 50 * 1024 * 1024
    syslog_mode: str = "full"  # full | ostrace
    ostrace_process: str = ""

    @classmethod
    def from_context(cls, ctx: "ExecutionContext", kwargs: dict[str, Any]) -> "LogCollectionOptions":
        from .....runtime import settings as app_settings

        def _bool_kw(*keys: str, default: bool) -> bool:
            for key in keys:
                raw = kwargs.get(key)
                if raw in (None, ""):
                    continue
                return str(raw).strip().lower() not in ("0", "false", "no", "off")
            return default

        enabled = _bool_kw(
            "collectDeviceLogs", "deviceLogs",
            default=app_settings.ios_monkey_device_logs_enabled(),
        )
        if ctx.get_var("__ios_monkey_device_logs__") is not None:
            val = str(ctx.get_var("__ios_monkey_device_logs__") or "").strip().lower()
            enabled = val not in ("0", "false", "no", "off")

        backend = str(
            kwargs.get("deviceLogsBackend")
            or ctx.get_var("__ios_monkey_device_logs_backend__")
            or app_settings.ios_monkey_device_logs_backend()
        ).strip().lower()
        if backend not in ("auto", "go-ios", "pmd3", "off"):
            backend = "auto"
        if backend == "off":
            enabled = False

        mode = str(
            kwargs.get("syslogMode")
            or ctx.get_var("__ios_monkey_syslog_mode__")
            or app_settings.ios_monkey_syslog_mode()
        ).strip().lower()
        if mode not in ("full", "ostrace"):
            mode = "full"

        ostrace_proc = str(
            kwargs.get("ostraceProcess")
            or ctx.get_var("__ios_monkey_ostrace_process__")
            or app_settings.ios_monkey_ostrace_process()
        ).strip()

        return cls(
            enabled=enabled,
            backend=backend,
            syslog_enabled=_bool_kw(
                "collectSyslog", default=app_settings.ios_monkey_syslog_enabled(),
            ),
            crash_enabled=_bool_kw(
                "collectCrash", default=app_settings.ios_monkey_crash_collect_enabled(),
            ),
            filter_bundle=app_settings.ios_monkey_syslog_filter_bundle(),
            syslog_max_bytes=app_settings.ios_monkey_syslog_max_bytes(),
            syslog_mode=mode,
            ostrace_process=ostrace_proc,
        )


@dataclass
class DeviceLogSummary:
    backend: str = ""
    syslogPath: str = ""
    syslogFilteredPath: str = ""
    syslogBytes: int = 0
    syslogFilteredLines: int = 0
    crashNewCount: int = 0
    crashRelevantCount: int = 0
    crashFiles: list[str] = field(default_factory=list)
    crashError: str = ""
    syslogError: str = ""
    startedAt: str = ""
    stoppedAt: str = ""
    syslogMode: str = "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "syslogPath": self.syslogPath,
            "syslogFilteredPath": self.syslogFilteredPath,
            "syslogBytes": self.syslogBytes,
            "syslogFilteredLines": self.syslogFilteredLines,
            "crashNewCount": self.crashNewCount,
            "crashRelevantCount": self.crashRelevantCount,
            "crashFiles": list(self.crashFiles),
            "crashError": self.crashError,
            "syslogError": self.syslogError,
            "startedAt": self.startedAt,
            "stoppedAt": self.stoppedAt,
            "syslogMode": self.syslogMode,
        }


class DeviceLogCollector:
    """Context manager：Monkey 期间并行采集设备日志。"""

    def __init__(
        self,
        udid: str,
        bundle_id: str,
        report_root: str,
        options: LogCollectionOptions,
        *,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.udid = udid
        self.bundle_id = bundle_id
        self.report_root = report_root
        self.options = options
        self.log = log or (lambda _m: None)
        self.device_dir = os.path.join(report_root, "device")
        self.crashes_dir = os.path.join(self.device_dir, "crashes")
        self._syslog_proc = None
        self._backend_module = goios_backend
        self._backend_name = ""
        self._before_crashes: set[str] = set()
        self._started_at = ""
        self._active = False
        self.last_summary: DeviceLogSummary | None = None

    def __enter__(self) -> "DeviceLogCollector":
        if self.options.enabled:
            self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._active:
            self.stop()

    @property
    def active(self) -> bool:
        return self._active

    def _pick_backend(self) -> tuple[str, Any]:
        pref = self.options.backend
        if pref == "go-ios":
            return "go-ios", goios_backend
        if pref == "pmd3":
            return "pymobiledevice3", pmd3_backend
        if goios_backend.available():
            return "go-ios", goios_backend
        return "pymobiledevice3", pmd3_backend

    def _write_crash_ls(self, name: str, text: str) -> None:
        os.makedirs(self.crashes_dir, exist_ok=True)
        path = os.path.join(self.crashes_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text or "")

    def _snapshot_crashes(self) -> set[str]:
        if not self.options.crash_enabled:
            return set()
        # noinspection PyBroadException
        try:
            r = self._backend_module.run_capture(
                self._backend_module.crash_ls_cmd(self.udid), timeout=90,
            )
            text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
            self._write_crash_ls("before.ls.txt", text)
            return parse_crash_ls(text)
        except Exception as exc:
            self.log(f"Monkey 设备日志：crash 快照失败（忽略）: {exc}")
            return set()

    def start(self) -> None:
        if self._active or not self.options.enabled:
            return
        os.makedirs(self.device_dir, exist_ok=True)
        self._backend_name, self._backend_module = self._pick_backend()
        self._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._active = True

        self._before_crashes = self._snapshot_crashes()

        if self.options.syslog_enabled:
            use_ostrace = (
                self.options.syslog_mode == "ostrace"
                and self._backend_name == "go-ios"
            )
            raw_name = "syslog.ostrace.txt" if use_ostrace else "syslog.raw.txt"
            raw_path = os.path.join(self.device_dir, raw_name)
            # noinspection PyBroadException
            try:
                if use_ostrace:
                    process = self.options.ostrace_process or self._guess_process(self.bundle_id)
                    self._syslog_proc = goios_backend.start_ostrace(
                        self.udid, raw_path,
                        process=process,
                        match=self.bundle_id,
                        log=self.log,
                    )
                else:
                    self._syslog_proc = self._backend_module.start_syslog(
                        self.udid, raw_path, log=self.log,
                    )
                time.sleep(0.3)
                if self._syslog_proc.poll() is not None:
                    raise RuntimeError(f"syslog 进程过早退出 code={self._syslog_proc.returncode}")
            except (OSError, RuntimeError) as exc:
                self.log(f"Monkey 设备日志：{self._backend_name} syslog 失败，尝试回退…")
                goios_backend.stop_syslog(self._syslog_proc)
                self._syslog_proc = None
                if self._backend_name == "go-ios" and self.options.backend == "auto":
                    self._backend_name = "pymobiledevice3"
                    self._backend_module = pmd3_backend
                    try:
                        self._syslog_proc = pmd3_backend.start_syslog(
                            self.udid, raw_path, log=self.log,
                        )
                    except Exception as exc2:
                        self.log(f"Monkey 设备日志：pmd3 syslog 也失败（忽略）: {exc2}")
                else:
                    self.log(f"Monkey 设备日志：syslog 不可用（忽略）: {exc}")

        meta = {
            "backend": self._backend_name,
            "startedAt": self._started_at,
            "udid": self.udid,
            "bundleId": self.bundle_id,
            "syslogMode": self.options.syslog_mode,
        }
        with open(os.path.join(self.device_dir, "collection.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _guess_process(bundle_id: str) -> str:
        parts = [p for p in (bundle_id or "").split(".") if p]
        return parts[-1] if parts else ""

    def _stop_syslog_only(self) -> None:
        """只停止本模块拥有的 syslog 子进程。"""
        if self._backend_name == "go-ios":
            goios_backend.stop_syslog(self._syslog_proc)
        else:
            pmd3_backend.stop_syslog(self._syslog_proc)
        self._syslog_proc = None

    def _filter_syslog(self, raw_path: str, filtered_path: str) -> int:
        if not self.options.filter_bundle or not os.path.isfile(raw_path):
            return 0
        bid = (self.bundle_id or "").lower()
        if not bid:
            return 0
        short = bid.split(".")[-1] if "." in bid else bid
        needles = {bid, bid.replace(".", "-")}
        if len(short) >= 4:
            needles.add(short)
        count = 0
        with open(raw_path, "rb") as src, open(filtered_path, "w", encoding="utf-8", errors="replace") as dst:
            from .textcodec import decode_syslog_line

            for line in src:
                text = decode_syslog_line(line)
                low = text.lower()
                if any(n in low for n in needles):
                    dst.write(text.rstrip("\r\n") + "\n")
                    count += 1
        return count

    def _collect_crashes(self, summary: DeviceLogSummary) -> None:
        if not self.options.crash_enabled:
            return
        new_dir = os.path.join(self.crashes_dir, "new")
        os.makedirs(new_dir, exist_ok=True)
        # noinspection PyBroadException
        try:
            if self._backend_name == "go-ios":
                r = self._backend_module.run_capture(
                    self._backend_module.crash_ls_cmd(self.udid), timeout=90,
                )
                after_text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
                self._write_crash_ls("after.ls.txt", after_text)
                after_set = parse_crash_ls(after_text)
                new_names = diff_new(self._before_crashes, after_set)
                if new_names:
                    pattern = "*"
                    self._backend_module.run_capture(
                        self._backend_module.crash_cp_cmd(self.udid, pattern, new_dir),
                        timeout=180,
                    )
            else:
                pmd3_backend.run_capture(
                    pmd3_backend.crash_pull_cmd(self.udid, new_dir),
                    timeout=180,
                )

            pulled = list_crash_files(new_dir)
            rel_files = [os.path.join("device", "crashes", "new", n) for n in pulled]
            relevant = [n for n in pulled if is_relevant_crash(n, self.bundle_id)]
            summary.crashNewCount = len(pulled)
            summary.crashRelevantCount = len(relevant)
            summary.crashFiles = rel_files

            manifest = {
                "newFiles": pulled,
                "relevantFiles": relevant,
                "bundleId": self.bundle_id,
            }
            with open(os.path.join(self.crashes_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            summary.crashError = str(exc)
            self.log(f"Monkey 设备日志：crash 拉取失败（忽略）: {exc}")

    def stop(self) -> DeviceLogSummary:
        summary = DeviceLogSummary(
            backend=self._backend_name,
            startedAt=self._started_at,
            stoppedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            syslogMode=self.options.syslog_mode,
        )
        if not self._active:
            return summary

        self._stop_syslog_only()

        raw_path = os.path.join(
            self.device_dir,
            "syslog.ostrace.txt" if self.options.syslog_mode == "ostrace" else "syslog.raw.txt",
        )
        filtered_path = os.path.join(self.device_dir, "syslog.filtered.txt")
        if os.path.isfile(raw_path):
            size = os.path.getsize(raw_path)
            if size > self.options.syslog_max_bytes > 0:
                # noinspection PyBroadException
                try:
                    with open(raw_path, "rb") as f:
                        f.seek(-self.options.syslog_max_bytes, os.SEEK_END)
                        tail = f.read()
                    with open(raw_path, "wb") as f:
                        f.write(b"...[truncated]\n")
                        f.write(tail)
                    size = os.path.getsize(raw_path)
                except OSError as exc:
                    summary.syslogError = f"truncate: {exc}"
            summary.syslogBytes = size
            summary.syslogPath = (
                "device/syslog.ostrace.txt"
                if self.options.syslog_mode == "ostrace"
                else "device/syslog.raw.txt"
            )
            summary.syslogFilteredLines = self._filter_syslog(raw_path, filtered_path)
            if summary.syslogFilteredLines > 0:
                summary.syslogFilteredPath = os.path.join("device", "syslog.filtered.txt")

        self._collect_crashes(summary)

        meta_path = os.path.join(self.device_dir, "collection.json")
        meta: dict[str, Any] = {}
        # noinspection PyBroadException
        try:
            with open(meta_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            pass
        meta.update(summary.to_dict())
        meta["stoppedAt"] = summary.stoppedAt
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        self._active = False
        self.last_summary = summary
        self.log(
            f"Monkey 设备日志完成: backend={summary.backend} "
            f"syslog={summary.syslogBytes}B crashNew={summary.crashNewCount}"
        )
        return summary
