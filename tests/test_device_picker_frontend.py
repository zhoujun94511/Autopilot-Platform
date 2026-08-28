"""执行路径 DevicePicker：批跑 / 计划复用，不依赖设备运维侧栏。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"


def test_device_pick_helpers_exist():
    text = (FE / "composables" / "devicePick.ts").read_text(encoding="utf-8")
    assert "export function parseUdids" in text
    assert "export function filterDevicesForPick" in text
    assert "export function serializeUdids" in text


def test_device_picker_component_modes():
    text = (FE / "components" / "DevicePicker.vue").read_text(encoding="utf-8")
    assert "自动分配" in text
    assert "指定设备" in text
    assert "filterDevicesForPick" in text
    assert "手填设备编号" in text
    # 不得把运维动作塞进执行 picker
    assert "onToggleDeviceMaintenance" not in text
    assert "onReleaseDevice" not in text
    assert "/maintenance" not in text
    assert "/release" not in text


def test_job_and_schedule_reuse_device_picker():
    fields = (FE / "components" / "common" / "RunTargetFields.vue").read_text(
        encoding="utf-8"
    )
    assert "DevicePicker" in fields
    assert "model.device_udids" in fields

    job = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert "RunTargetFields" in job
    assert ':model="form"' in job

    sched = (FE / "components" / "SchedulesPanel.vue").read_text(encoding="utf-8")
    assert "RunTargetFields" in sched
    assert ':model="scheduleForm"' in sched
    assert "compact" in sched

    enqueue = (FE / "components" / "design" / "EnqueueRunConfigCard.vue").read_text(
        encoding="utf-8"
    )
    assert "RunTargetFields" in enqueue


def test_device_board_is_org_view_not_project_filter():
    filters = (FE / "composables" / "useDeviceBoardFilters.ts").read_text(encoding="utf-8")
    assert "filterProjectId" not in filters
    assert "listDevicesPage(undefined" in filters
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "fetchAllDevices(undefined)" in actions
    assert "fetchDeviceBoard(undefined" in actions
    assert "dispatchDevices" in actions
    job = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert ':devices="dispatchDevices"' in job
    panel = (FE / "components" / "DevicesPanel.vue").read_text(encoding="utf-8")
    assert "组织在线设备" in panel
    assert "不跟顶栏项目走" in panel
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    assert "不绑某个项目" in runners
    assert "请先在顶栏选择设备归属组织" not in runners
    assert "filterProjectId" not in runners
    assert "pagedDetailDevices" in runners
    assert "pagedInventory" in runners
    assert "NESTED_DEVICE_PAGE_SIZE" in runners
    assert "displayName(d)" in runners
    assert "d.name || d.model || d.udid" not in runners
    picker = (FE / "components" / "DevicePicker.vue").read_text(encoding="utf-8")
    assert "displayName(d)" in picker
    assert "d.name || d.model || d.udid" not in picker
    assert "platformBadgeLabel" in picker
    assert 'toUpperCase()' not in picker


def test_ai_chat_optional_project_generate_requires_write():
    chat = (FE / "components" / "design" / "DesignChatPanel.vue").read_text(encoding="utf-8")
    assert "generalMode" in chat
    assert "onSendEphemeral" in chat
    gen = (FE / "components" / "design" / "DesignCaseGenerateCard.vue").read_text(
        encoding="utf-8"
    )
    assert "canEditProject" in gen
    assert "落库" in gen


def test_schedules_tab_refreshes_devices():
    text = (FE / "composables" / "mcRefreshScopes.ts").read_text(encoding="utf-8")
    # schedules 行需含 devices，否则普通用户看不见侧栏时计划表单无候选
    assert 'schedules: ["schedules", "projects", "artifacts", "app-builds", "devices"]' in text or (
        "schedules:" in text and '"devices"' in text.split("schedules:")[1].split("\n")[0]
    )
