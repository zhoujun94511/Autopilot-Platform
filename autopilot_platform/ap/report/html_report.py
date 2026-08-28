"""HTML 报告生成（Jinja2，内联 CSS/JS，自包含无外部资源）。

信息架构（主次分明）：
1. 结论条（通过/失败 + 关键数字）
2. 失败焦点（有失败时置顶）
3. 用例总览
4. 步骤明细（失败用例默认展开）
5. 执行环境（默认折叠）

输出默认写入工程 ``reports/autopilot_report_YYYYMMDD_HHMMSS.html``，并同步
``autopilot_report_latest.html``。
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field, is_dataclass, replace
from datetime import datetime
from typing import Any, Optional

from importlib.metadata import PackageNotFoundError, version

# noinspection PyUnresolvedReferences
from jinja2 import Template

from ..engine.suite import SuiteResult
from .fail_class import classify_step

try:
    from lxml import etree
except ImportError:
    etree = None  # type: ignore[misc,assignment]


_STATUS_COLOR = {
    "PASS": "#0d7a3f",
    "FAIL": "#b42318",
    "NOIMPL": "#b54708",
    "SKIP": "#475467",
    "CANCEL": "#475467",
}
_STATUS_BG = {
    "PASS": "#ecfdf3",
    "FAIL": "#fef3f2",
    "NOIMPL": "#fffaeb",
    "SKIP": "#f2f4f7",
    "CANCEL": "#f2f4f7",
}
_STATUS_LABEL = {
    "PASS": "通过",
    "FAIL": "失败",
    "NOIMPL": "未实现",
    "SKIP": "跳过",
    "CANCEL": "取消",
}


@dataclass
class ReportMeta:
    """报告页眉与环境信息（由 UI/CLI 注入，缺省字段自动补全）。"""

    project_dir: str = ""
    project_name: str = ""
    suite_name: str = ""
    generated_at: str = ""
    started_at: str = ""
    fault_strategy: str = ""
    platforms: list[str] = field(default_factory=list)
    backend_mode: str = ""
    devices: dict[str, str] = field(default_factory=dict)  # android/ios → udid
    host: str = ""
    python_version: str = ""
    autopilot_version: str = ""
    case_paths: list[str] = field(default_factory=list)


def format_duration(ms: int) -> str:
    """毫秒 → 人类可读时长。"""
    if ms < 0:
        ms = 0
    if ms < 1000:
        return f"{ms} ms"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.2f} s"
    mins, rem = divmod(sec, 60)
    if mins < 60:
        return f"{int(mins)} m {rem:.1f} s"
    hours, rem_m = divmod(mins, 60)
    return f"{int(hours)} h {int(rem_m)} m {rem_m % 1 * 60:.0f} s"


def report_filename(when: Optional[datetime] = None, prefix: str = "autopilot_report") -> str:
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}.html"


def default_report_path(project_dir: str, when: Optional[datetime] = None) -> str:
    """工程下 ``reports/`` 目录 + 时间戳文件名。"""
    reports_dir = os.path.join(project_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    return os.path.join(reports_dir, report_filename(when))


def _keyword_names() -> dict[str, str]:
    errors: tuple[type[BaseException], ...] = (ImportError, OSError, AttributeError, KeyError)
    if etree is not None:
        errors = (*errors, etree.LxmlError)
    try:
        from ..metadata.keyword_meta import load_catalog  # 延迟：报告里显示中文名，失败则回落 id

        return {kid: (m.name or kid) for kid, m in load_catalog().by_id.items()}
    except errors:
        return {}


def _autopilot_version() -> str:
    try:
        return version("autopilot")
    except PackageNotFoundError:
        return "dev"


def _case_duration(rr) -> int:
    if getattr(rr, "duration_ms", 0):
        return rr.duration_ms
    return sum(getattr(s, "duration_ms", 0) or 0 for s in rr.results)


def _first_failure(suite: SuiteResult):
    for rr in suite.results:
        for sr in rr.results:
            if sr.status == "FAIL":
                return rr, sr
    return None, None


def _step_fail_label(sr) -> str:
    label = str(getattr(sr, "fail_reason_label", "") or "").strip()
    if label:
        return label
    code = str(getattr(sr, "fail_reason", "") or "").strip()
    return code


def _step_fail_class_label(sr) -> str:
    return str(classify_step(sr).get("fail_class_label") or "").strip()


def _step_attribution_label(sr) -> str:
    return str(classify_step(sr).get("attribution_label") or "").strip()


def _shot_src(b64: str) -> str:
    data = str(b64 or "").strip()
    if not data:
        return ""
    if data.startswith("data:image/"):
        return data
    if data.startswith("/9j/"):
        return f"data:image/jpeg;base64,{data}"
    return f"data:image/png;base64,{data}"


def _display_step(sr: Any) -> Any:
    """HTML 内嵌缩略图；不改原始 StepResult（磁盘路径仍是原图）。"""
    before = str(getattr(sr, "screenshot_before", "") or "")
    after = str(getattr(sr, "screenshot", "") or "")
    if not before and not after:
        return sr
    if not is_dataclass(sr) or isinstance(sr, type):
        return sr
    from .thumb import thumbnail_b64  # 延迟：无截图步骤不解码图像

    return replace(
        sr,
        screenshot_before=thumbnail_b64(before) if before else "",
        screenshot=thumbnail_b64(after) if after else "",
    )


def _qa_review_for_case(rr: Any) -> dict[str, Any]:
    if bool(getattr(rr, "passed", False)):
        return {}
    from .fail_review import review_failed_case  # 延迟：仅失败用例事后二审

    steps: list[dict[str, Any]] = []
    for s in getattr(rr, "results", None) or []:
        steps.append({
            "status": str(getattr(s, "status", "") or ""),
            "attribution": str(getattr(s, "attribution", "") or ""),
            "fail_class": str(getattr(s, "fail_class", "") or ""),
            "fail_reason": str(getattr(s, "fail_reason", "") or ""),
            "error_message": str(getattr(s, "message", "") or ""),
            "screenshot_path": str(getattr(s, "screenshot_path", "") or ""),
            "screenshot_before_path": str(getattr(s, "screenshot_before_path", "") or ""),
            "screenshot": str(getattr(s, "screenshot", "") or ""),
        })
    return review_failed_case({"status": "failed", "steps": steps})


def _step_http_line(sr) -> str:
    url = str(getattr(sr, "http_url", "") or "").strip()
    try:
        status = int(getattr(sr, "http_status", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    try:
        elapsed = int(getattr(sr, "http_elapsed_ms", 0) or 0)
    except (TypeError, ValueError):
        elapsed = 0
    if not url and not status:
        return ""
    bits: list[str] = []
    if status:
        bits.append(str(status))
    if url:
        bits.append(url)
    if elapsed:
        bits.append(format_duration(elapsed))
    return " · ".join(bits)


def _case_search_text(rr, kw_names: dict[str, str]) -> str:
    parts = [
        getattr(rr, "case_name", "") or "",
        getattr(rr, "source_path", "") or "",
        getattr(rr, "tag", "") or "",
        getattr(rr, "platform", "") or "",
    ]
    for sr in getattr(rr, "results", None) or []:
        kid = str(getattr(sr, "keyword_id", "") or "")
        parts.append(kid)
        parts.append(kw_names.get(kid, ""))
        parts.append(getattr(sr, "comment", "") or "")
        parts.append(getattr(sr, "http_url", "") or "")
        status = getattr(sr, "http_status", 0) or 0
        if status:
            parts.append(str(status))
        parts.append(_step_fail_class_label(sr))
        parts.append(_step_attribution_label(sr))
    return " ".join(str(p) for p in parts if p)


def _build_context(
    suite: SuiteResult, generated_at: str = "", meta: Optional[ReportMeta] = None
) -> dict[str, Any]:
    meta = meta or ReportMeta()
    if not meta.generated_at:
        meta.generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not meta.suite_name:
        meta.suite_name = suite.name
    if not meta.host:
        meta.host = platform.node()
    if not meta.python_version:
        meta.python_version = sys.version.split()[0]
    if not meta.autopilot_version:
        meta.autopilot_version = _autopilot_version()
    if not meta.project_name and meta.project_dir:
        meta.project_name = os.path.basename(meta.project_dir.rstrip("/\\")) or meta.project_dir

    cc = suite.case_counts()
    sc = suite.step_counts()
    pass_rate = suite.pass_rate()
    fail_rr, fail_sr = _first_failure(suite)
    kw_names = _keyword_names()
    fail_case_id = ""

    cases = []
    failed_cases = []
    for i, rr in enumerate(suite.results, 1):
        cid = f"case-{i}"
        if fail_rr is rr:
            fail_case_id = cid
        counts = rr.counts()
        qa = _qa_review_for_case(rr)
        case = {
            "index": i,
            "id": cid,
            "name": rr.case_name,
            "passed": rr.passed,
            "counts": counts,
            "source_path": getattr(rr, "source_path", "") or "",
            "platform": getattr(rr, "platform", "") or "",
            "tag": getattr(rr, "tag", "") or "",
            "device_udid": getattr(rr, "device_udid", "") or "",
            "worker_slot": getattr(rr, "worker_slot", -1),
            "duration_ms": _case_duration(rr),
            "steps": [_display_step(s) for s in rr.results],
            "qa_review": qa,
            "fail_count": counts.get("FAIL", 0),
            "pass_count": counts.get("PASS", 0),
            "first_fail_label": "",
            "search_text": _case_search_text(rr, kw_names),
        }
        if not rr.passed:
            for sr in rr.results:
                if sr.status == "FAIL":
                    case["first_fail_label"] = _step_fail_label(sr) or (
                        sr.comment or sr.keyword_id or "步骤失败"
                    )
                    break
            failed_cases.append(case)
        cases.append(case)

    fail_qa_review: dict[str, Any] = {}
    for case in cases:
        if case["id"] == fail_case_id:
            fail_qa_review = case.get("qa_review") or {}
            break

    return {
        "suite": suite,
        "meta": meta,
        "generated_at": meta.generated_at,
        "cc": cc,
        "sc": sc,
        "pass_rate": pass_rate,
        "overall_passed": cc["failed"] == 0,
        "cases": cases,
        "failed_cases": failed_cases,
        "fail_case": fail_rr,
        "fail_step": fail_sr,
        "fail_step_label": _step_fail_label(fail_sr) if fail_sr else "",
        "fail_case_id": fail_case_id,
        "fail_qa_review": fail_qa_review,
        "shot_src": _shot_src,
        "kw_names": kw_names,
        "total_steps": sum(sc.values()),
        "fmt_dur": format_duration,
        "color": lambda s: _STATUS_COLOR.get(s, "#333"),
        "status_bg": lambda s: _STATUS_BG.get(s, "#f5f5f5"),
        "status_label": lambda s: _STATUS_LABEL.get(s, s),
        "step_fail_label": _step_fail_label,
        "step_fail_class_label": _step_fail_class_label,
        "step_attribution_label": _step_attribution_label,
        "http_line": _step_http_line,
    }


_TEMPLATE = Template("""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ meta.suite_name }} — 测试报告</title>
<style>
:root{
  --bg:#f4f5f7; --surface:#fff; --text:#101828; --muted:#667085;
  --line:#e4e7ec; --line-strong:#d0d5dd;
  --pass:#027a48; --pass-bg:#ecfdf3; --pass-border:#abefc6;
  --fail:#b42318; --fail-bg:#fef3f2; --fail-border:#fecdca;
  --accent:#175cd3; --accent-soft:#eff4ff;
  --radius:10px;
  --font: "IBM Plex Sans","Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  --mono: "IBM Plex Mono",Consolas,"Cascadia Mono",monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; font-family:var(--font); color:var(--text); background:var(--bg);
  line-height:1.5; font-size:14px; -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1100px; margin:0 auto; padding:20px 20px 56px}
.topbar{
  position:sticky; top:0; z-index:20; margin:0 -20px 18px; padding:10px 20px;
  background:rgba(244,245,247,.92); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line); display:flex; gap:10px; flex-wrap:wrap;
  align-items:center; justify-content:space-between;
}
.topbar .brand{font-size:12px; color:var(--muted); letter-spacing:.02em}
.topbar .actions{display:flex; gap:6px; flex-wrap:wrap; align-items:center}
.search{
  appearance:none; border:1px solid var(--line-strong); background:var(--surface);
  color:var(--text); border-radius:8px; padding:6px 10px; font:inherit; font-size:12px;
  min-width:180px; width:min(280px,42vw);
}
.search:focus{outline:2px solid #b2ccff; outline-offset:1px}
.http-line{font-family:var(--mono); font-size:11.5px; color:#344054; margin-top:4px; word-break:break-all}
.btn{
  appearance:none; border:1px solid var(--line-strong); background:var(--surface);
  color:var(--text); border-radius:8px; padding:6px 10px; font:inherit; font-size:12px;
  cursor:pointer; text-decoration:none; display:inline-flex; align-items:center;
}
.btn:hover{background:#f9fafb}
.btn.active{background:var(--accent-soft); border-color:#b2ccff; color:#1849a9}
.btn.primary{background:var(--accent); border-color:var(--accent); color:#fff}
.btn.primary:hover{filter:brightness(.96); text-decoration:none}

/* —— 1. 结论（主） —— */
.verdict{
  background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
  padding:18px 20px; margin-bottom:14px;
}
.verdict.ok{border-color:var(--pass-border); background:linear-gradient(180deg,#fff 0%, var(--pass-bg) 140%)}
.verdict.bad{border-color:var(--fail-border); background:linear-gradient(180deg,#fff 0%, var(--fail-bg) 140%)}
.verdict-row{display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; align-items:flex-start}
.verdict h1{margin:0; font-size:1.35rem; font-weight:700; letter-spacing:-.02em; line-height:1.25}
.verdict .meta-line{margin:6px 0 0; color:var(--muted); font-size:12.5px}
.chip{
  display:inline-flex; align-items:center; gap:6px; padding:7px 12px; border-radius:999px;
  font-weight:700; font-size:13px; white-space:nowrap; border:1px solid transparent;
}
.chip.ok{background:var(--pass-bg); color:var(--pass); border-color:var(--pass-border)}
.chip.bad{background:var(--fail-bg); color:var(--fail); border-color:var(--fail-border)}
.kpis{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:14px}
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.kpi{
  border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:#fff;
}
.kpi .n{font-size:1.35rem; font-weight:750; font-variant-numeric:tabular-nums; line-height:1.1}
.kpi .l{margin-top:3px; font-size:11.5px; color:var(--muted)}
.kpi.pass .n{color:var(--pass)} .kpi.fail .n{color:var(--fail)}
.rate{
  margin-top:12px; height:6px; border-radius:99px; background:#e4e7ec; overflow:hidden; display:flex;
}
.rate>i{display:block; height:100%}
.rate .p{background:var(--pass)} .rate .f{background:var(--fail)}

/* —— 2. 失败焦点 —— */
.section{margin-bottom:14px}
.section-h{
  display:flex; align-items:baseline; justify-content:space-between; gap:10px;
  margin:0 0 8px;
}
.section-h h2{margin:0; font-size:13px; font-weight:700; letter-spacing:.02em; color:#344054}
.section-h .hint{font-size:12px; color:var(--muted)}
.panel{
  background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
  padding:14px 16px;
}
.fail-box{border-color:var(--fail-border); background:#fff}
.fail-lead{font-size:13px; margin:0 0 10px}
.fail-lead strong{color:var(--fail)}
.fail-list{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px}
.fail-list a{
  display:flex; justify-content:space-between; gap:10px; align-items:baseline;
  padding:8px 10px; border:1px solid var(--line); border-radius:8px; color:inherit;
  background:#fff;
}
.fail-list a:hover{border-color:#fecdca; background:var(--fail-bg); text-decoration:none}
.fail-list .name{font-weight:650; font-size:13px}
.fail-list .why{font-size:12px; color:var(--muted); text-align:right; max-width:55%;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.qa-review{margin:10px 0 12px; padding:10px 12px; border:1px dashed var(--line-strong);
  border-radius:8px; background:#f9fafb}
.qa-review-h{font-size:12px; font-weight:700; color:#344054; margin-bottom:6px}
.qa-review ul{margin:0; padding-left:18px}
.qa-review li{font-size:12.5px; color:#475467; margin:3px 0}
.msg{
  white-space:pre-wrap; word-break:break-word; font-size:12px; color:#344054;
  margin:8px 0 0; padding:8px 10px; background:#f9fafb; border-radius:8px; border:1px solid var(--line);
}
.mono{font-family:var(--mono); font-size:12px}

/* —— 3. 总览表 —— */
table.data{width:100%; border-collapse:collapse; font-size:13px}
table.data th, table.data td{
  text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top;
}
table.data th{
  font-size:11.5px; font-weight:650; color:var(--muted); background:#f9fafb;
  position:sticky; top:46px; z-index:1;
}
table.data tr:last-child td{border-bottom:none}
table.data tr:hover td{background:#fafbfc}
table.data tr.row-fail td{background:#fffbfa}
.badge{
  display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px;
}
.badge.pass{color:var(--pass); background:var(--pass-bg)}
.badge.fail{color:var(--fail); background:var(--fail-bg)}
.badge.muted{color:var(--muted); background:#f2f4f7}
.st{
  display:inline-block; min-width:48px; text-align:center; font-size:11px; font-weight:700;
  padding:2px 7px; border-radius:6px;
}

/* —— 4. 步骤明细 —— */
.case{
  background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
  margin-bottom:10px; overflow:hidden;
}
.case>summary{
  cursor:pointer; list-style:none; padding:12px 14px; display:flex;
  justify-content:space-between; align-items:flex-start; gap:12px; font-weight:650;
}
.case>summary::-webkit-details-marker{display:none}
.case>summary::before{content:""; width:6px; height:6px; border-radius:50%;
  margin-top:7px; flex:0 0 auto; background:var(--pass)}
.case.bad>summary::before{background:var(--fail)}
.case-meta{font-size:12px; color:var(--muted); font-weight:400; margin-top:3px}
.case-right{text-align:right; font-size:12px; color:var(--muted)}
.case .body{border-top:1px solid var(--line)}
.kw{font-family:var(--mono); font-size:12px; color:#344054}
.kw-name{color:var(--muted); font-size:11.5px; margin-top:2px}
.attr{
  display:inline-block; font-size:11px; padding:1px 6px; border-radius:4px;
  background:#f2f4f7; color:#475467; margin-right:4px;
}
.shot summary{cursor:pointer; color:var(--accent); font-size:12px; margin-top:6px}
.shot img{max-width:100%; margin-top:8px; border:1px solid var(--line); border-radius:8px}
.shot-pair{display:flex; gap:10px; flex-wrap:wrap; align-items:flex-start}
.shot-pair figure{margin:8px 0 0; flex:1 1 220px; max-width:48%}
.shot-pair figcaption{font-size:11px; color:var(--muted); margin-top:4px}

/* —— 5. 环境（次） —— */
details.env>summary{
  cursor:pointer; list-style:none; font-size:13px; font-weight:700; color:#344054;
}
details.env>summary::-webkit-details-marker{display:none}
.meta-grid{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:8px 16px; font-size:13px; margin-top:12px;
}
.meta-grid dt{color:var(--muted); margin:0 0 2px; font-size:11.5px}
.meta-grid dd{margin:0 0 8px; word-break:break-all}
.footer{margin-top:22px; text-align:center; font-size:11.5px; color:var(--muted)}
@media print{
  .topbar{position:static; background:#fff}
  .case{break-inside:avoid}
}
</style>
</head>
<body>
<div class="wrap">

 <div class="topbar">
  <div class="brand">AutoPilot 测试报告</div>
  <div class="actions">
   <button type="button" class="btn" onclick="expandAll(true)">展开全部</button>
   <button type="button" class="btn" onclick="expandAll(false)">折叠全部</button>
   <input type="search" class="search" id="q" placeholder="搜索用例 / 关键字"
          oninput="applyFilter()" aria-label="搜索用例或关键字">
   <button type="button" class="btn" id="btn-fail" onclick="toggleFailOnly()">仅失败用例</button>
   {% if fail_step %}<a class="btn primary" href="#failures">失败焦点</a>{% endif %}
  </div>
 </div>

 <!-- 1. 结论 -->
 <header class="verdict {{ 'ok' if overall_passed else 'bad' }}">
  <div class="verdict-row">
   <div>
    <h1>{{ meta.suite_name }}</h1>
    <p class="meta-line">
     {% if meta.project_name %}{{ meta.project_name }} · {% endif %}
     {{ generated_at }} · 耗时 {{ fmt_dur(suite.duration_ms) }}
    </p>
   </div>
   <div class="chip {{ 'ok' if overall_passed else 'bad' }}">
    {% if overall_passed %}全部通过{% else %}存在失败{% endif %}
    · {{ '%.1f'|format(pass_rate) }}%
   </div>
  </div>
  <div class="kpis">
   <div class="kpi"><div class="n">{{ cc.total }}</div><div class="l">用例</div></div>
   <div class="kpi pass"><div class="n">{{ cc.passed }}</div><div class="l">通过</div></div>
   <div class="kpi fail"><div class="n">{{ cc.failed }}</div><div class="l">未通过</div></div>
   <div class="kpi"><div class="n">{{ fmt_dur(suite.duration_ms) }}</div><div class="l">总耗时</div></div>
  </div>
  <div class="rate" aria-hidden="true">
   <i class="p" style="width:{{ pass_rate }}%"></i>
   {% if pass_rate < 100 %}<i class="f" style="width:{{ 100 - pass_rate }}%"></i>{% endif %}
  </div>
 </header>

 <!-- 2. 失败焦点（主路径） -->
 {% if fail_step %}
 <section class="section" id="failures">
  <div class="section-h">
   <h2>失败焦点</h2>
   <span class="hint">{{ failed_cases|length }} 个未通过用例 · 先看这里</span>
  </div>
  <div class="panel fail-box">
   <p class="fail-lead">
    <strong>首个失败</strong>
    — 用例 <a href="#{{ fail_case_id }}">{{ fail_case.case_name }}</a>
    · <span class="mono">{{ fail_step.keyword_id }}</span>
    {% if kw_names.get(fail_step.keyword_id) %}（{{ kw_names[fail_step.keyword_id] }}）{% endif %}
    {% if fail_step_label %} · <span class="attr">{{ fail_step_label }}</span>{% endif %}
    {% if fail_step and step_fail_class_label(fail_step) %}
    · <span class="attr">{{ step_fail_class_label(fail_step) }}</span>
    {% endif %}
    {% if fail_step and step_attribution_label(fail_step) %}
    · <span class="attr">{{ step_attribution_label(fail_step) }}</span>
    {% endif %}
   </p>
   {% if fail_step.comment %}<div>{{ fail_step.comment }}</div>{% endif %}
   {% if fail_step.remark %}<div class="case-meta">备注：{{ fail_step.remark }}</div>{% endif %}
   {% if fail_step and http_line(fail_step) %}<div class="http-line">{{ http_line(fail_step) }}</div>{% endif %}
   {% if fail_step.message %}<div class="msg">{{ fail_step.message }}</div>{% endif %}
   {% if fail_qa_review and fail_qa_review.issues %}
   <div class="qa-review">
    <div class="qa-review-h">事后二审（加注，未改结论）</div>
    <ul>
     {% for issue in fail_qa_review.issues %}
     <li>{{ issue }}</li>
     {% endfor %}
    </ul>
   </div>
   {% endif %}
   {% if failed_cases|length > 1 %}
   <ul class="fail-list" style="margin-top:12px">
    {% for c in failed_cases %}
    <li><a href="#{{ c.id }}">
     <span class="name">#{{ c.index }} {{ c.name }}</span>
     <span class="why">{{ c.first_fail_label or (c.fail_count ~ ' 步失败') }}</span>
    </a></li>
    {% endfor %}
   </ul>
   {% endif %}
  </div>
 </section>
 {% endif %}

 <!-- 3. 用例总览 -->
 <section class="section" id="overview">
  <div class="section-h">
   <h2>用例总览</h2>
   <span class="hint">步骤 {{ total_steps }} · 通过 {{ sc.get('PASS',0) }} · 失败 {{ sc.get('FAIL',0) }}{% if sc.get('SKIP',0) %} · 跳过 {{ sc.get('SKIP',0) }}{% endif %}{% if sc.get('NOIMPL',0) %} · 未实现 {{ sc.get('NOIMPL',0) }}{% endif %}</span>
  </div>
  <div class="panel" style="padding:0; overflow:auto">
   <table class="data" id="case-overview">
    <thead><tr>
     <th style="width:40px">#</th>
     <th>用例</th>
     <th style="width:72px">结果</th>
     <th style="width:72px">平台</th>
     <th style="width:100px">步骤</th>
     <th style="width:88px">耗时</th>
     <th>路径</th>
    </tr></thead>
    <tbody>
    {% for c in cases %}
    <tr class="{{ 'row-fail' if not c.passed else '' }}"
        data-passed="{{ '1' if c.passed else '0' }}"
        data-search="{{ c.search_text }}">
     <td>{{ c.index }}</td>
     <td>
      <a href="#{{ c.id }}">{{ c.name }}</a>
      {% if c.tag %}<div class="case-meta">{{ c.tag }}</div>{% endif %}
     </td>
     <td>{% if c.passed %}<span class="badge pass">通过</span>{% else %}<span class="badge fail">未通过</span>{% endif %}</td>
     <td>{{ c.platform or '—' }}</td>
     <td>{{ c.pass_count }}/{{ c.steps|length }}{% if c.fail_count %} <span class="badge fail">{{ c.fail_count }}</span>{% endif %}</td>
     <td>{{ fmt_dur(c.duration_ms) }}</td>
     <td class="mono" style="font-size:11px">{{ c.source_path or '—' }}</td>
    </tr>
    {% endfor %}
    </tbody>
   </table>
  </div>
 </section>

 <!-- 4. 步骤明细 -->
 <section class="section" id="details">
  <div class="section-h">
   <h2>步骤明细</h2>
   <span class="hint">失败用例默认展开</span>
  </div>

  {% for c in cases %}
  <details class="case {{ 'bad' if not c.passed else '' }}" id="{{ c.id }}"
           data-passed="{{ '1' if c.passed else '0' }}"
           data-search="{{ c.search_text }}"
           {% if not c.passed %}open{% endif %}>
   <summary>
    <div>
     <div>#{{ c.index }} {{ c.name }}</div>
     <div class="case-meta">
      {% if c.platform %}{{ c.platform }} · {% endif %}
      {% if c.device_udid %}{{ c.device_udid }} · {% endif %}
      {{ c.steps|length }} 步 · {{ fmt_dur(c.duration_ms) }}
     </div>
    </div>
    <div class="case-right">
     {% if c.passed %}<span class="badge pass">通过</span>{% else %}<span class="badge fail">未通过</span>{% endif %}
     <div style="margin-top:4px">{{ c.pass_count }} 通过{% if c.fail_count %} / {{ c.fail_count }} 失败{% endif %}</div>
    </div>
   </summary>
   <div class="body" style="overflow:auto">
    {% if c.qa_review and c.qa_review.issues %}
    <div class="qa-review">
     <div class="qa-review-h">事后二审（加注，未改结论）</div>
     <ul>
      {% for issue in c.qa_review.issues %}
      <li>{{ issue }}</li>
      {% endfor %}
     </ul>
    </div>
    {% endif %}
    <table class="data">
     <thead><tr>
      <th style="width:36px">#</th>
      <th style="width:64px">状态</th>
      <th style="width:44px">轮次</th>
      <th style="width:180px">关键字</th>
      <th>说明</th>
      <th style="width:96px">耗时</th>
      <th>信息</th>
     </tr></thead>
     <tbody>
     {% for s in c.steps %}
     <tr class="{{ 'row-fail' if s.status == 'FAIL' else '' }}">
      <td>{{ loop.index }}</td>
      <td><span class="st" style="color:{{ color(s.status) }};background:{{ status_bg(s.status) }}">{{ status_label(s.status) }}</span></td>
      <td>{{ s.loop_index if s.loop_index is not none else '—' }}</td>
      <td>
       <div class="kw">{{ s.keyword_id }}</div>
       {% if kw_names.get(s.keyword_id) %}<div class="kw-name">{{ kw_names[s.keyword_id] }}</div>{% endif %}
      </td>
      <td>
       {{ s.comment or '—' }}
       {% if s.remark %}<div class="case-meta">{{ s.remark }}</div>{% endif %}
       {% if s.status == 'FAIL' and step_fail_label(s) %}
       <div style="margin-top:4px"><span class="attr">{{ step_fail_label(s) }}</span></div>
       {% endif %}
       {% if s.status == 'FAIL' and step_fail_class_label(s) %}
       <div style="margin-top:4px"><span class="attr">{{ step_fail_class_label(s) }}</span></div>
       {% endif %}
       {% if s.status == 'FAIL' and step_attribution_label(s) %}
       <div style="margin-top:4px"><span class="attr">{{ step_attribution_label(s) }}</span></div>
       {% endif %}
      </td>
      <td>{{ fmt_dur(s.duration_ms) }}</td>
      <td>
       {% if http_line(s) %}<div class="http-line">{{ http_line(s) }}</div>{% endif %}
       {% if s.message %}<div class="msg" style="margin:0">{{ s.message }}</div>{% endif %}
       {% if s.screenshot_before or s.screenshot %}
       <details class="shot" open>
        <summary>{% if s.screenshot_before and s.screenshot %}操作前 / 失败后{% elif s.screenshot_before %}操作前{% else %}失败截图{% endif %}</summary>
        <div class="shot-pair">
         {% if s.screenshot_before %}
         <figure><img alt="操作前" src="{{ shot_src(s.screenshot_before) }}"><figcaption>操作前</figcaption></figure>
         {% endif %}
         {% if s.screenshot %}
         <figure><img alt="失败后" src="{{ shot_src(s.screenshot) }}"><figcaption>失败后</figcaption></figure>
         {% endif %}
        </div>
       </details>
       {% elif not s.message and not http_line(s) %}—{% endif %}
      </td>
     </tr>
     {% endfor %}
     </tbody>
    </table>
   </div>
  </details>
  {% endfor %}
 </section>

 <!-- 5. 环境（次要，默认折叠） -->
 <section class="section" id="env">
  <div class="panel">
   <details class="env">
    <summary>执行环境（次要信息）</summary>
    <dl class="meta-grid">
     {% if meta.project_name %}<div><dt>工程</dt><dd>{{ meta.project_name }}</dd></div>{% endif %}
     {% if meta.project_dir %}<div><dt>工程路径</dt><dd class="mono">{{ meta.project_dir }}</dd></div>{% endif %}
     <div><dt>套件</dt><dd>{{ meta.suite_name }}</dd></div>
     {% if meta.started_at %}<div><dt>开始</dt><dd>{{ meta.started_at }}</dd></div>{% endif %}
     <div><dt>结束</dt><dd>{{ generated_at }}</dd></div>
     <div><dt>总耗时</dt><dd>{{ fmt_dur(suite.duration_ms) }}</dd></div>
     {% if meta.fault_strategy %}<div><dt>失败策略</dt><dd>{{ meta.fault_strategy }}</dd></div>{% endif %}
     {% if meta.platforms %}<div><dt>平台</dt><dd>{{ meta.platforms|join(' / ') }}</dd></div>{% endif %}
     {% if meta.backend_mode %}<div><dt>运行环境</dt><dd class="mono">{{ meta.backend_mode }}</dd></div>{% endif %}
     {% if meta.devices %}
     <div><dt>设备</dt><dd class="mono">
      {% for key, udid in meta.devices|dictsort %}<div>{{ key }}：{{ udid }}</div>{% endfor %}
     </dd></div>
     {% endif %}
     <div><dt>主机</dt><dd>{{ meta.host }}</dd></div>
     <div><dt>Python</dt><dd>{{ meta.python_version }}</dd></div>
     <div><dt>AutoPilot</dt><dd>{{ meta.autopilot_version }}</dd></div>
    </dl>
   </details>
  </div>
 </section>

 <div class="footer">AutoPilot {{ meta.autopilot_version }} · 单文件 HTML，可离线归档</div>
</div>
<script>
function expandAll(open){
  document.querySelectorAll('.case').forEach(function(el){ el.open = open; });
}
var failOnly=false;
function applyFilter(){
  var qEl=document.getElementById('q');
  var q=((qEl && qEl.value) || '').trim().toLowerCase();
  document.querySelectorAll('.case, #case-overview tbody tr').forEach(function(el){
    var pass=el.getAttribute('data-passed')==='1';
    var hay=(el.getAttribute('data-search')||'').toLowerCase();
    var ok=(!failOnly || !pass) && (!q || hay.indexOf(q)>=0);
    el.style.display=ok?'':'none';
  });
}
function toggleFailOnly(){
  failOnly=!failOnly;
  var btn=document.getElementById('btn-fail');
  if(btn) btn.classList.toggle('active', failOnly);
  applyFilter();
}
</script>
</body></html>""")


def render_report(
    suite: SuiteResult, generated_at: str = "", meta: Optional[ReportMeta] = None
) -> str:
    ctx = _build_context(suite, generated_at, meta)
    return _TEMPLATE.render(**ctx)


def write_report(
    suite: SuiteResult,
    path: str,
    generated_at: str = "",
    meta: Optional[ReportMeta] = None,
    write_latest: bool = True,
) -> str:
    if meta is None:
        meta = ReportMeta()
    if generated_at:
        meta.generated_at = generated_at
    html = render_report(suite, meta.generated_at, meta)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    if write_latest and meta.project_dir:
        latest = os.path.join(meta.project_dir, "autopilot_report_latest.html")
        with open(latest, "w", encoding="utf-8") as f:
            f.write(html)
    return path
