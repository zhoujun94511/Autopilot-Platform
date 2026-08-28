"""全仓弹框约定：原生 dialog 禁用、确认唯一宿主、自制遮罩不得充当确认层。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
NOTIFY_MD = ROOT / "autopilot_platform" / "frontend" / "NOTIFY.md"

# 自制遮罩只允许业务表单 / 预览 / 查看器，禁止做成第二套确认框。
ALLOWED_HOMEMADE_OVERLAYS = {
    "components/ResourcePoolsPanel.vue": "设备池表单",
    "components/JobLogViewer.vue": "任务日志查看器",
    "components/projects/CreateProjectModal.vue": "创建项目表单",
    "components/JobsPanel.vue": "新建批跑表单",
    "components/ArtifactsPanel.vue": "上传制品表单",
    "components/SchedulesPanel.vue": "计划表单",
    "components/remote/files/RemoteFilePreviewModal.vue": "文件预览",
}

_OVERLAY_CLASS_RE = re.compile(
    r"""class=["'][^"']*(?:modal-mask|modal-backdrop|remote-file-preview-overlay)[^"']*["']"""
)


def test_confirm_host_is_only_app_notify_host():
    writers = []
    for path in FE.rglob("*.vue"):
        text = path.read_text(encoding="utf-8")
        if "notifyConfirm" in text or "notifyPrompt" in text or "notifyCopy" in text:
            writers.append(path.relative_to(FE).as_posix())
    assert writers == ["components/AppNotifyHost.vue"]
    host = (FE / "components" / "AppNotifyHost.vue").read_text(encoding="utf-8")
    assert "import ApModal" in host
    assert "stack" in host


def test_homemade_overlays_are_classified_and_not_confirm_hosts():
    found: dict[str, str] = {}
    for path in FE.rglob("*.vue"):
        rel = path.relative_to(FE).as_posix()
        text = path.read_text(encoding="utf-8")
        if "ap-modal-backdrop" in text:
            continue
        if not _OVERLAY_CLASS_RE.search(text):
            continue
        found[rel] = text
    assert set(found) == set(ALLOWED_HOMEMADE_OVERLAYS), (
        "homemade overlays changed; classify as form/viewer or migrate to ApModal:\n"
        + "\n".join(sorted(set(found) ^ set(ALLOWED_HOMEMADE_OVERLAYS)))
    )
    for rel, text in found.items():
        assert "notifyConfirm" not in text, rel
        assert "window.confirm" not in text, rel
        assert re.search(r"(?:window\.)?(?:alert|confirm|prompt)\s*\(", text) is None, rel


def test_stacked_confirm_sits_above_file_preview():
    styles = (FE / "styles.css").read_text(encoding="utf-8")
    assert re.search(
        r"\.ap-modal-backdrop\.stacked\s*\{[^}]*z-index:\s*10003", styles, re.S
    )
    preview = (FE / "components" / "remote" / "files" / "RemoteFilePreviewModal.vue").read_text(
        encoding="utf-8"
    )
    assert "z-index: 10002" in preview
    select = (FE / "components" / "common" / "ApSelect.vue").read_text(encoding="utf-8")
    assert "z-index: 10004" in select
    md = NOTIFY_MD.read_text(encoding="utf-8")
    assert "10003" in md
    assert "自制" in md


def test_destructive_actions_use_project_confirm_not_native():
    """扩大范围后补上的缺口：删模板 / 回收超时任务 / 清空设备日志。"""
    create = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert "async function onDeleteTemplate" in create
    assert "confirmDialog(`删除模板" in create

    exec_src = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    start = exec_src.find("export async function onReclaimStale")
    body = exec_src[start : start + 500]
    assert "confirmDialog(" in body
    assert "回收超时" in body

    logs = (FE / "composables" / "remote" / "useRemoteDeviceLogs.ts").read_text(
        encoding="utf-8"
    )
    start = logs.find("async function clearAll")
    body = logs[start : start + 500]
    assert "confirmDialog(" in body
    assert "logcat -c" in body


def test_job_report_opens_in_page_modal_not_window_open():
    exec_src = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    start = exec_src.find("export async function onViewReport")
    body = exec_src[start : start + 900]
    assert "window.open" not in body
    assert "document.write" not in body
    assert "reportView.value" in body
    assert 'sandbox="allow-scripts"' in (
        FE / "components" / "JobReportViewer.vue"
    ).read_text(encoding="utf-8")
    app = (FE / "App.vue").read_text(encoding="utf-8")
    assert "JobReportViewer" in app
    md = NOTIFY_MD.read_text(encoding="utf-8")
    assert "window.open" in md
    assert "JobReportViewer" in md


def test_frontend_forbids_window_open_and_document_write():
    hits: list[str] = []
    for path in FE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ts", ".vue", ".js", ".html"}:
            continue
        rel = path.relative_to(FE).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "<!--")):
                continue
            if "window.open" in stripped or "document.write" in stripped:
                hits.append(f"{rel}:{i}:{stripped}")
    assert not hits, "reports must use JobReportViewer; do not window.open:\n" + "\n".join(
        hits
    )
