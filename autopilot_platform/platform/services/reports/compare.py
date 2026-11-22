"""用例级对比再导出。

实现在 ``ap/report/compare.py``（与 IDE ``autopilot/report/compare.py`` 双仓同步）。
本模块只做同包再导出，避免检查器解析 ``ap.report`` 包初始化失败时标红。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ....ap.report.compare import compare_case_lists, refine_verdict


def compare_reports(
    db: Session, left_job_id: str, right_job_id: str, auth=None
) -> dict:
    from .storage import compare_reports as _compare_reports

    return _compare_reports(db, left_job_id, right_job_id, auth=auth)


__all__ = ["compare_reports", "compare_case_lists", "refine_verdict"]
