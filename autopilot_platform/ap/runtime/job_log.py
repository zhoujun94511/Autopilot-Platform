"""并发 Job 日志隔离：按线程绑定 job id。

parallel worker 与 execute 不在同一线程，worker 入口需自行 set。
"""

from __future__ import annotations

import threading

_tls = threading.local()


def get_job_log_id() -> str:
    return str(getattr(_tls, "job_id", "") or "")


def set_job_log_id(job_id: str) -> str:
    prev = get_job_log_id()
    _tls.job_id = str(job_id or "")
    return prev


def reset_job_log_id(prev: str) -> None:
    _tls.job_id = str(prev or "")


class _JobLogBinder:
    @staticmethod
    def get() -> str:
        return get_job_log_id()

    @staticmethod
    def set(job_id: str) -> str:
        return set_job_log_id(job_id)

    @staticmethod
    def reset(token: str) -> None:
        reset_job_log_id(token)


JOB_LOG_ID = _JobLogBinder()
