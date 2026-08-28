"""执行报告：Jinja2 生成自包含 HTML（零外部依赖，内置 HTML 报告）。

``from ap.report.fail_class import classify_failure`` 不得顺带加载
``html_report``（后者顶栏引用 ``engine.suite``，会与 ``executor`` 成环）。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .compare import compare_case_lists, refine_verdict
from .fail_class import (
    classify_attribution,
    classify_failure,
    classify_step,
    scan_attributions,
    scan_fail_classes,
)

if TYPE_CHECKING:
    from .html_report import (
        ReportMeta as ReportMeta,
        default_report_path as default_report_path,
        render_report as render_report,
        report_filename as report_filename,
        write_report as write_report,
    )

__all__ = [
    "ReportMeta",
    "default_report_path",
    "render_report",
    "report_filename",
    "write_report",
    "compare_case_lists",
    "refine_verdict",
    "classify_attribution",
    "classify_failure",
    "classify_step",
    "scan_attributions",
    "scan_fail_classes",
]

_HTML_EXPORTS = frozenset({
    "ReportMeta",
    "default_report_path",
    "render_report",
    "report_filename",
    "write_report",
})


def __getattr__(name: str) -> Any:
    if name in _HTML_EXPORTS:
        mod = import_module(f"{__name__}.html_report")
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
