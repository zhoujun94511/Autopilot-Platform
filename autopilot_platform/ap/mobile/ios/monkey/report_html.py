"""iOS Monkey HTML 报告（自包含，无外部资源）。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from jinja2 import Template


def _read_json(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _read_events(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _tail_lines(path: str, n: int = 100) -> str:
    if not os.path.isfile(path):
        return ""
    from .device_logs.textcodec import decode_syslog_text

    with open(path, "rb") as f:
        data = f.read()
    text = decode_syslog_text(data)
    lines = text.splitlines(keepends=True)
    return "".join(lines[-n:])


def _list_error_dirs(report_dir: str) -> list[dict[str, str]]:
    errors_root = os.path.join(report_dir, "errors")
    if not os.path.isdir(errors_root):
        return []
    out: list[dict[str, str]] = []
    for name in sorted(os.listdir(errors_root)):
        folder = os.path.join(errors_root, name)
        if not os.path.isdir(folder):
            continue
        exc_path = os.path.join(folder, "exception.txt")
        shot = os.path.join(folder, "screenshot.png")
        out.append({
            "name": name,
            "exception": _tail_lines(exc_path, 20).strip() if os.path.isfile(exc_path) else "",
            "screenshot": f"errors/{name}/screenshot.png" if os.path.isfile(shot) else "",
        })
    return out


def build_context(report_dir: str) -> dict[str, Any]:
    summary = _read_json(os.path.join(report_dir, "summary.json"))
    events = _read_events(os.path.join(report_dir, "events.jsonl"))
    device_logs = summary.get("deviceLogs") if isinstance(summary.get("deviceLogs"), dict) else {}
    # 预览优先读 raw/ostrace（正确解码 GBK 进程名）；filtered 可能是旧版 UTF-8 replace 乱码
    raw_rel = str(device_logs.get("syslogPath") or "")
    filtered_rel = str(device_logs.get("syslogFilteredPath") or "")
    preview_path = ""
    for rel in (raw_rel, filtered_rel):
        if not rel:
            continue
        abs_path = os.path.join(report_dir, rel.replace("/", os.sep))
        if os.path.isfile(abs_path):
            preview_path = abs_path
            break
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "events": events,
        "device_logs": device_logs,
        "errors": _list_error_dirs(report_dir),
        "syslog_preview": _tail_lines(preview_path, 80),
        "report_dir": report_dir,
    }


_TEMPLATE = Template("""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>iOS Monkey — {{ summary.get('bundleId','') }}</title>
<style>
body{font-family:Segoe UI,system-ui,sans-serif;margin:0;background:#f4f6f8;color:#222}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
h1{margin:0 0 8px;font-size:1.5rem}
.meta{color:#666;font-size:.9rem;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
.card{background:#fff;border-radius:8px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card .k{font-size:.75rem;color:#666;text-transform:uppercase}
.card .v{font-size:1.35rem;font-weight:600;margin-top:4px}
.pass{color:#1b8a3e}.warn{color:#e65100}.fail{color:#d32f2f}
section{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
section h2{margin:0 0 12px;font-size:1.05rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#fafafa}
pre{background:#111;color:#eee;padding:12px;border-radius:6px;overflow:auto;font-size:.75rem;max-height:320px}
.err img{max-width:240px;border:1px solid #ddd;border-radius:4px}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.75rem;background:#eee}
</style></head><body><div class="wrap">
<h1>iOS Monkey 报告</h1>
<div class="meta">{{ generated_at }} · {{ report_dir }}</div>
<div class="cards">
  <div class="card"><div class="k">结果</div><div class="v {% if summary.get('result')=='passed' %}pass{% elif 'fail' in (summary.get('result') or '') %}fail{% else %}warn{% endif %}">{{ summary.get('result','') }}</div></div>
  <div class="card"><div class="k">事件数</div><div class="v">{{ summary.get('eventCount',0) }}</div></div>
  <div class="card"><div class="k">耗时</div><div class="v">{{ summary.get('durationSec',0) }}s</div></div>
  <div class="card"><div class="k">Backend</div><div class="v">{{ summary.get('backend','') }}</div></div>
  <div class="card"><div class="k">Crash 新增</div><div class="v">{{ device_logs.get('crashNewCount',0) }}</div></div>
</div>
<section><h2>运行参数</h2>
<p>Bundle: <code>{{ summary.get('bundleId','') }}</code> · Policy: {{ summary.get('policy','') }} · Seed: {{ summary.get('seed','') }}</p>
<p>Alert: {{ summary.get('alertHandledCount',0) }} · Stuck: {{ summary.get('stuckRecoverCount',0) }} · Watchdog: {{ summary.get('watchdogRecoverCount',0) }} · Errors: {{ summary.get('errorCount',0) }}</p>
{% if device_logs %}
<p>设备日志 backend={{ device_logs.get('backend','') }} · syslog {{ device_logs.get('syslogBytes',0) }} bytes · 相关 crash {{ device_logs.get('crashRelevantCount',0) }}</p>
{% endif %}
</section>
<section><h2>事件时间线</h2>
<table><thead><tr><th>#</th><th>时间</th><th>动作</th><th>结果</th><th>详情</th></tr></thead><tbody>
{% for e in events %}
<tr>
  <td>{{ e.get('index','') }}</td>
  <td>{{ e.get('time','') }}</td>
  <td>{{ e.get('action','') }}</td>
  <td>{{ e.get('result','') }}</td>
  <td>{% if e.get('label') %}label={{ e.get('label') }} {% endif %}{% if e.get('x') is not none %}({{ e.get('x') }},{{ e.get('y') }}){% endif %}{% if e.get('error') %} {{ e.get('error') }}{% endif %}</td>
</tr>
{% endfor %}
</tbody></table></section>
{% if errors %}
<section><h2>异常现场</h2>
{% for err in errors %}
<div class="err" style="margin-bottom:16px">
  <div><span class="tag">{{ err.name }}</span></div>
  <pre>{{ err.exception | e }}</pre>
  {% if err.screenshot %}<img src="{{ err.screenshot }}" alt="screenshot">{% endif %}
</div>
{% endfor %}
</section>
{% endif %}
{% if syslog_preview %}
<section><h2>Syslog 预览</h2><pre>{{ syslog_preview | e }}</pre></section>
{% endif %}
</div></body></html>
""")


def render_monkey_report(report_dir: str) -> str:
    """生成 ``report.html``，返回绝对路径。"""
    ctx = build_context(report_dir)
    html_text = _TEMPLATE.render(**ctx)
    out_path = os.path.join(report_dir, "report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return out_path
