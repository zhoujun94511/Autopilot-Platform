"""前端通知分层约定白盒：列表动作走 notify，表单结果走内联 msg。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
NOTIFY_MD = ROOT / "autopilot_platform" / "frontend" / "NOTIFY.md"


def test_notify_convention_docs_exist():
    text = (FE / "composables" / "useNotify.ts").read_text(encoding="utf-8")
    assert "通知分层约定" in text
    assert "无表单上下文" in text
    assert "绑定当前表单" in text
    assert NOTIFY_MD.is_file()
    md = NOTIFY_MD.read_text(encoding="utf-8")
    assert "notify" in md
    assert "xxxMsg" in md or "内联" in md


def _fn_body(src: str, name: str, span: int = 900) -> str:
    start = src.find(f"export async function {name}")
    assert start >= 0, name
    return src[start : start + span]


def test_list_actions_use_notify_not_form_msg():
    """同类列表动作：成功/失败走 Toast，不串写创建表单旁的 xxxMsg。"""
    exec_src = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    admin_src = (FE / "composables" / "mcAdminActions.ts").read_text(encoding="utf-8")
    ops_src = (FE / "composables" / "mcOpsActions.ts").read_text(encoding="utf-8")

    retry = _fn_body(exec_src, "onRetryJob")
    assert 'notify(`已重试' in retry or 'notify("已重试' in retry
    assert "jobMsg.value" not in retry

    cancel = _fn_body(exec_src, "onCancelJob")
    assert "notify(" in cancel
    assert "jobMsg.value" not in cancel

    for name in ("onDeleteArtifact", "onDeleteAppBuild", "onRenameAppBuild"):
        body = _fn_body(exec_src, name)
        assert "notify(" in body, name
        assert "artMsg.value" not in body and "appBuildMsg.value" not in body, name

    for name in ("onToggleUserDisabled", "onResetUserPassword", "onDeleteUser"):
        body = _fn_body(admin_src, name)
        assert "notify(" in body, name
        assert "userMsg.value" not in body, name

    revoke = _fn_body(ops_src, "onRevokeAcl")
    assert 'notify("已撤销分享"' in revoke or "notify('已撤销分享'" in revoke


def test_form_bound_results_still_use_inline_msg():
    """表单提交结果仍走内联通道（不强制改 Toast）。"""
    exec_src = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    create_job = _fn_body(exec_src, "onCreateJob", span=2000)
    assert "jobMsg" in create_job

    upload = _fn_body(exec_src, "onUpload", span=500)
    assert "artMsg" in upload

    admin_src = (FE / "composables" / "mcAdminActions.ts").read_text(encoding="utf-8")
    create_user = _fn_body(admin_src, "onCreateUser")
    assert "userMsg" in create_user

    # 单一 Toast 宿主
    app = (FE / "App.vue").read_text(encoding="utf-8")
    assert "AppNotifyHost" in app
    assert not re.search(r"window\.(alert|confirm|prompt)\s*\(", exec_src)


_NATIVE_DIALOG_RE = re.compile(r"(?:window\.)?(?:alert|confirm|prompt)\s*\(")
_PROJECT_DIALOG_RE = re.compile(r"\b(?:confirm|prompt)Dialog\s*\(")
_SRC_SUFFIXES = {".ts", ".vue", ".js", ".tsx", ".jsx", ".html", ".mjs", ".cjs"}
_SKIP_DIR_NAMES = {
    "node_modules",
    "dist",
    "archive",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "htmlcov",
    "coverage",
    ".vite",
    "vendor",
}


def _iter_web_sources(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SRC_SUFFIXES:
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def test_frontend_forbids_native_browser_dialogs():
    """确认/输入/复制必须走 confirmDialog / promptDialog / showCopyDialog，禁止原生弹框。"""
    notify = (FE / "composables" / "useNotify.ts").read_text(encoding="utf-8")
    assert "export function confirmDialog" in notify
    assert "export function promptDialog" in notify
    assert "export function showCopyDialog" in notify
    assert "禁止直接调用浏览器原生弹框" in notify

    host = (FE / "components" / "AppNotifyHost.vue").read_text(encoding="utf-8")
    assert "notifyConfirm" in host
    assert "notifyPrompt" in host
    assert "notifyCopy" in host
    assert "ApModal" in host

    hits: list[str] = []
    for path in _iter_web_sources(ROOT):
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "<!--", "#")):
                continue
            if _PROJECT_DIALOG_RE.search(line):
                continue
            if _NATIVE_DIALOG_RE.search(line):
                hits.append(f"{rel}:{i}:{stripped}")
    assert not hits, "native browser dialogs must use confirmDialog/promptDialog:\n" + "\n".join(
        hits
    )

    md = NOTIFY_MD.read_text(encoding="utf-8")
    assert "window.alert" in md
    assert "confirmDialog" in md
    assert "全仓" in md


def test_toast_kind_ttl_and_stack_tokens():
    """Toast 对齐成熟项目：warn 类型、按 kind TTL、顶栏避让、主题 token。"""
    notify = (FE / "composables" / "useNotify.ts").read_text(encoding="utf-8")
    assert 'NotifyKind = "info" | "success" | "error" | "warn"' in notify
    assert "TOAST_MAX = 4" in notify
    assert "DEFAULT_TOAST_KINDS" in notify
    assert "success: false" in notify
    assert "warn: true" in notify
    assert "error: true" in notify
    assert "export function createNotifier" in notify
    assert "export function setNotifyPolicy" in notify
    assert "success: 2800" in notify
    assert "warn: 5000" in notify
    assert "error: 5000" in notify
    assert "export function pauseToast" in notify
    assert "export function resumeToast" in notify

    host = (FE / "components" / "AppNotifyHost.vue").read_text(encoding="utf-8")
    assert "var(--topbar-height" in host
    assert "--ok-soft-border" in host
    assert "--danger-soft-border" in host
    assert "--warning-soft-border" in host
    assert "--info-soft-border" in host
    assert "--elevated-shadow" in host
    assert 'aria-label="关闭通知"' in host
    assert "pauseToast" in host
    assert "resumeToast" in host
    assert "isAlertKind" in host
    assert "? 'alert' : 'status'" in host
    assert "? 'assertive' : 'polite'" in host
    assert "toast-warn-bg" in host

    styles = (FE / "styles.css").read_text(encoding="utf-8")
    assert "--topbar-height: 56px" in styles
    assert "--toast-warn-bg:" in styles

    md = NOTIFY_MD.read_text(encoding="utf-8")
    assert '"warn"' in md
    assert "最多 4" in md
    assert "DEFAULT_TOAST_KINDS" in notify or "只弹出" in md
    assert "createNotifier" in md or "useNotify({ success: true })" in md

    exec_src = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    remote = (FE / "components" / "RemoteDeviceDialog.vue").read_text(encoding="utf-8")
    assert 'notify("占用人尚未开启远程调试，暂无法旁观", "warn")' in exec_src
    assert 'notify(reason, "warn")' in remote


def _script_fn(src: str, name: str, span: int = 800) -> str:
    start = src.find(f"async function {name}")
    assert start >= 0, name
    return src[start : start + span]


def test_notify_alignment_silent_success_and_inline_validation():
    """审计对齐：列表静默成功补回执；表单校验不走 Toast；文件动作失败不双写。"""
    docs = (FE / "components" / "design" / "DesignDocsPanel.vue").read_text(encoding="utf-8")
    remove_doc = _script_fn(docs, "onRemove")
    assert "已删除文档" in remove_doc
    assert "info.value" in remove_doc
    remove_req = _script_fn(docs, "onRemoveReq")
    assert "已删除需求" in remove_req
    assert "info.value" in remove_req

    invite = (FE / "components" / "projects" / "ProjectInviteCard.vue").read_text(
        encoding="utf-8"
    )
    revoke = _script_fn(invite, "onRevoke")
    assert 'notify("已撤销邀请", "success")' in revoke
    assert "error.value = apiErrorMessage" not in revoke

    ios = (FE / "components" / "remote" / "RemoteIosControls.vue").read_text(encoding="utf-8")
    assert "function reportError" in ios
    assert "reportError(exc)" in _script_fn(ios, "checkAlert", 400)
    assert "reportError(exc)" in _script_fn(ios, "doAlert", 400)
    assert "reportError(exc)" in _script_fn(ios, "sendKey", 400)

    info = (FE / "components" / "remote" / "RemoteDeviceInfoPanel.vue").read_text(
        encoding="utf-8"
    )
    assert 'notify("复制失败，请检查浏览器剪贴板权限", "error")' in info
    logs = (FE / "composables" / "remote" / "useRemoteDeviceLogs.ts").read_text(
        encoding="utf-8"
    )
    assert 'notify("复制失败，请检查浏览器剪贴板权限", "error")' in logs

    files = (FE / "components" / "remote" / "RemoteFilesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "function toastError" in files
    assert "error.value = message" not in files

    pools = (FE / "components" / "ResourcePoolsPanel.vue").read_text(encoding="utf-8")
    assert 'formError.value = "请填写设备池名称"' in pools
    assert 'notify("请填写设备池名称"' not in pools

    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    assert 'notify("请勾选待注册设备"' not in runners
    assert "deviceActionResult.value =" in _script_fn(runners, "applyDeviceSelection", 500)
    assert 'provisionError.value = "请选择归属组织并填写节点 ID"' in runners
    assert 'notify("请选择归属组织并填写节点 ID"' not in runners

    app = (FE / "App.vue").read_text(encoding="utf-8")
    assert "Global Error Toast banner" not in app
    assert "shell.error，不是 Toast" in app
