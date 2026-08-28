"""设备占用：单表单弹窗 + ApModal 基座（替代三连 promptDialog）。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
EXEC_ACTIONS = FE / "composables" / "mcExecActions.ts"
RESERVE_COMPOSABLE = FE / "composables" / "useReserveDialog.ts"
RESERVE_DIALOG = FE / "components" / "ReserveDeviceDialog.vue"
AP_MODAL = FE / "components" / "ApModal.vue"
NOTIFY_HOST = FE / "components" / "AppNotifyHost.vue"
STYLES = FE / "styles.css"
DEVICES_SVC = (
    ROOT
    / "autopilot_platform"
    / "platform"
    / "services"
    / "execution"
    / "devices"
    / "scheduling.py"
)


def _reserve_action_body() -> str:
    src = EXEC_ACTIONS.read_text(encoding="utf-8")
    start = src.index("export async function onReserveDevice")
    end = src.index("export async function", start + 10)
    return src[start:end]


def test_reserve_flow_is_single_form_not_prompt_chain():
    body = _reserve_action_body()
    assert "openReserveDialog" in body
    assert "promptDialog" not in body
    # 数字编号菜单是 CLI 思维，GUI 必须用可点选项
    assert "用途编号" not in body
    assert "1 / 2 / 3 / 4" not in body
    # 标题/回执用人类可读设备名，不用裸 UDID
    assert "displayName(device)" in body


def test_reserve_composable_contract():
    assert RESERVE_COMPOSABLE.is_file()
    text = RESERVE_COMPOSABLE.read_text(encoding="utf-8")
    assert "export function openReserveDialog" in text
    assert "RESERVE_DURATION_PRESETS" in text
    assert "RESERVE_MAX_MINUTES = 1440" in text
    assert "RESERVE_MIN_MINUTES = 1" in text
    assert "export function durationLabel" in text


def test_purpose_tags_match_backend():
    """前端预设标签必须与后端 reason 前缀解析一致，否则占用摘要认不出用途。"""
    svc = DEVICES_SVC.read_text(encoding="utf-8")
    backend = set(re.findall(r'\("(\[[^]]+])", "[^"]+"\)', svc))
    assert backend, "后端未找到 _RESERVE_PURPOSE_TAGS"

    fe = RESERVE_COMPOSABLE.read_text(encoding="utf-8")
    frontend = set(re.findall(r'tag: "(\[[^]]+])"', fe))
    assert backend == frontend, f"用途标签漂移：后端 {backend} / 前端 {frontend}"


def test_reserve_dialog_form_semantics():
    assert RESERVE_DIALOG.is_file()
    src = RESERVE_DIALOG.read_text(encoding="utf-8")
    assert "ApModal" in src
    # chip 单选而非文本输编号
    assert "aria-pressed" in src
    assert "RESERVE_PURPOSES" in src
    assert "RESERVE_DURATION_PRESETS" in src
    # 校验实时化：非法值禁用主按钮，而不是提交后 toast 报错
    assert ':disabled="!minutes"' in src
    assert "ap-field-error" in src
    assert 'role="alert"' in src
    # 默认值齐全 → 打开即可确定
    assert "RESERVE_DEFAULT_MINUTES" in src
    assert "data-autofocus" in src
    # 到期时间预览
    assert "到期自动释放" in src


def test_ap_modal_base_a11y():
    assert AP_MODAL.is_file()
    src = AP_MODAL.read_text(encoding="utf-8")
    assert 'role="dialog"' in src
    assert 'aria-modal="true"' in src
    assert "aria-labelledby" in src
    assert 'ev.key === "Escape"' in src
    assert "@click.self" in src
    # 焦点陷阱 + 关闭后归还焦点
    assert 'ev.key !== "Tab"' in src
    assert "restoreTo" in src


def test_notify_host_delegates_to_ap_modal():
    src = NOTIFY_HOST.read_text(encoding="utf-8")
    assert "ApModal" in src
    # modal 结构与样式收敛到基座 / 全局，宿主只留 toast
    assert "ap-modal-backdrop" not in src
    assert 'role="dialog"' not in src
    assert ".ap-toast" in src

    app = (FE / "App.vue").read_text(encoding="utf-8")
    assert "ReserveDeviceDialog" in app


def test_modal_styles_are_global():
    """插槽内容属父组件作用域，modal/chip 样式必须全局否则命不中。"""
    styles = STYLES.read_text(encoding="utf-8")
    for cls in (
        ".ap-modal-backdrop",
        ".ap-modal.wide",
        ".ap-modal.xwide",
        ".ap-modal-actions",
        ".ap-btn:disabled",
        ".ap-chip",
        '.ap-chip[aria-pressed="true"]',
        ".ap-field-error",
    ):
        assert cls in styles, cls


def test_prompt_dialog_single_field_convention_documented():
    notify = (FE / "composables" / "useNotify.ts").read_text(encoding="utf-8")
    assert "禁止串联" in notify
    assert "useReserveDialog" in notify
