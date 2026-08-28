"""Runner 本机 Job 槽位：按设备互斥并发，而不是整机一条任务。"""

from __future__ import annotations

import threading


class JobSlotTracker:
    """同一 Runner 进程内：有 UDID 的 Job 只要设备集合不相交即可并行；

    无 UDID（web / 未指定设备）的 Job 彼此互斥，但可与设备 Job 并行。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, set[str]] = {}
        self._web_job_id: str = ""

    def has_any(self) -> bool:
        with self._lock:
            return bool(self._jobs)

    def has_web(self) -> bool:
        with self._lock:
            return bool(self._web_job_id)

    def job_ids(self) -> list[str]:
        with self._lock:
            return list(self._jobs)

    def busy_udids(self) -> set[str]:
        with self._lock:
            busy: set[str] = set()
            for udids in self._jobs.values():
                busy.update(udids)
            return busy

    def try_reserve(self, job_id: str, device_udids: list[str] | None) -> str:
        """成功返回空串；失败返回原因（不写入）。"""
        jid = (job_id or "").strip()
        if not jid:
            return "missing job id"
        udids = {str(u).strip() for u in (device_udids or []) if str(u).strip()}
        with self._lock:
            if jid in self._jobs:
                return f"job already reserved: {jid}"
            if not udids:
                if self._web_job_id:
                    return "host-exclusive job already running"
                self._web_job_id = jid
                self._jobs[jid] = set()
                return ""
            busy: set[str] = set()
            for owned in self._jobs.values():
                busy.update(owned)
            overlap = sorted(udids & busy)
            if overlap:
                return "devices busy: " + ",".join(overlap)
            self._jobs[jid] = udids
            return ""

    def release(self, job_id: str) -> None:
        jid = (job_id or "").strip()
        with self._lock:
            self._jobs.pop(jid, None)
            if self._web_job_id == jid:
                self._web_job_id = ""
