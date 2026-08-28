"""配置治理前端契约（C32）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"


def test_ops_config_webhook_allow_loopback_in_ui():
    cfg = (FE / "api" / "opsConfig.ts").read_text(encoding="utf-8")
    assert "MC_WEBHOOK_ALLOW_LOOPBACK" in cfg
    assert "运维中心优先" in cfg or "运维" in cfg


def test_start_dev_points_platform_at_vite():
    text = (ROOT / "start_dev.py").read_text(encoding="utf-8")
    assert "MC_FRONTEND_DEV_URL" in text
    assert "CLIENT_URL" in text
    assert "_auto_start_managed_runner" not in text
    assert "正在重启 Vite" in text
    assert "--reload-delay" in text


def test_vite_proxy_reads_mc_port():
    vite = (ROOT / "autopilot_platform" / "frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )
    assert "MC_PORT" in vite
    assert "127.0.0.1:8000" not in vite
    assert "ignored" in vite
    assert "**/*.py" in vite


def test_configuration_doc_exists():
    doc = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    assert "runtime_json" in doc or "运维配置中心" in doc


def test_frontend_bootstrap_module():
    boot = (FE / "api" / "bootstrap.ts").read_text(encoding="utf-8")
    assert "loadPlatformBootstrap" in boot
    assert "apiPath" in boot


def test_no_hardcoded_runner_8000_in_ui():
    runtime = (FE / "composables" / "platformRuntime.ts").read_text(encoding="utf-8")
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    assert "127.0.0.1:8000" not in runtime
    assert "127.0.0.1:8000" not in runners


def test_runner_onboarding_distinguishes_registration_from_managed_mode():
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    assert "接入新节点" in runners
    assert "管理测试设备" in runners
    assert "创建远程节点" in runners
    assert "注册所选" in runners
    assert "取消所选注册" in runners
    assert "Platform 同机托管" in runners
    assert "runner-empty-panel" in runners
    assert "runner-onboarding" not in runners
    assert "runner-recovery-banner" not in runners
    assert "needsManagedRecovery" not in runners
    assert "visibleCapabilities(r)" in runners
    assert 'r.has_token ? "轮换令牌" : "签发令牌"' in runners
    assert "/api/v1/runners/managed/device-probe" in runners
    assert "/device-inventory" in runners
    assert "/device-selection" in runners
    assert "/api/v1/runners/provision" in runners
    assert "toggleAllInventory" in runners
    assert 'applyDeviceSelection("register")' in runners or "applyDeviceSelection('register')" in runners
    assert ":disabled=\"Boolean(d.rejection_reason)\"" in runners
    assert "请勾选待注册设备" in runners
    assert "请勾选要取消注册的设备" in runners
    assert "请先在顶栏选择设备归属组织" not in runners
    assert "请选择本机节点的归属组织" in runners
    assert "将注册到组织" in runners
    assert "runnerSourceLabel" in runners
    assert "在线设备" in runners
    assert "创建远程节点需要先有组织" in runners
    assert "请选择归属组织并填写节点 ID" in runners
    assert "provisionOrgId" in runners
    assert "resolvedRegisterOrgId" in runners
    assert "willStartManagedOnRegister" in runners
    assert "已注册" in runners
    assert "已取消" in runners
    assert "占用中" in runners
    assert "occupancy_username" in runners
    assert "occupancy_start_at" in runners
    assert "occupancy_end_at" in runners
    assert "任务完成时" in runners
    assert 'class="occupancy-card"' in runners
    assert 'class="occupancy-grid"' in runners
    assert "占用人" in runners
    assert "开始时间" in runners
    assert "预占到期" in runners
    assert "任务名称" in runners
    assert "任务 ID" in runners
    assert "pagedDetailDevices" in runners
    assert "pagedInventory" in runners
    assert "NESTED_DEVICE_PAGE_SIZE" in runners
    assert "搜索编号 / 型号" in runners
    assert "无匹配设备，请调整搜索" in runners
    assert "platformBadgeLabel" in runners
    assert "d.platform.toUpperCase()" not in runners
    assert "registeredOk" in runners
    assert "needsOrgOnRegister" in runners
    assert "所选设备已注册，无需重复登记" in runners
    assert "attempt < 10" not in runners
    assert "/scope" in runners.split("async function applyDeviceSelection", 1)[1].split(
        "function openProvision", 1
    )[0]
    assert "deviceManagerOpen.value = false" in runners.split("async function applyDeviceSelection", 1)[1].split(
        "function openProvision", 1
    )[0]


def test_runner_device_register_uses_node_org_not_header_filter():
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "请先在顶栏选择设备归属组织" not in runners
    assert "boundDeviceOrgId" in runners
    assert "registerOrgId" in runners
    assert "filterOrgId.value.trim()" not in runners.split("async function applyDeviceSelection", 1)[1].split(
        "function openProvision", 1
    )[0]
    assert "existing || filterOrgId.value.trim()" in actions
    assert 'body: oid ? JSON.stringify({ org_id: oid }) : undefined' in actions


def test_platform_admin_register_not_blocked_by_org_gate():
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    block = runners.split("const needsOrgOnRegister = computed(", 1)[1].split(");", 1)[0]
    assert "!caps.canOps" in block.replace(" ", "")
    pools = (FE / "components" / "ResourcePoolsPanel.vue").read_text(encoding="utf-8")
    assert "不是「在线设备」列表" in pools
    hub = (FE / "components" / "DevicesHub.vue").read_text(encoding="utf-8")
    assert "不是在线设备列表" in hub


def test_device_register_flow_frontend_has_no_inventory_poll_or_duplicate_submit():
    runners = (FE / "components" / "RunnersPanel.vue").read_text(encoding="utf-8")
    util = (FE / "utils" / "inventoryRegister.ts").read_text(encoding="utf-8")
    apply = runners.split("async function applyDeviceSelection", 1)[1].split(
        "function openProvision", 1
    )[0]
    assert apply.count("device-inventory") == 1
    assert "for (let attempt" not in apply
    assert "setTimeout" not in apply
    assert "partitionCheckedUdids" in apply
    assert "checkedPendingUdids" in runners
    assert "checkedRegisteredUdids" in runners
    assert "inventoryStatusFilter" in runners
    assert "deviceIsRegistered" in runners
    assert "inventory-status-chips" in runners
    assert "inventory-row-registered" in runners
    assert "默认只列出待注册设备" in runners
    assert "所选设备已注册，无需重复登记" in apply
    assert "所选设备尚未注册" in apply
    assert "needsOrgOnRegister" in apply
    assert 'v-else-if="needsOrgOnRegister"' in runners
    assert "willStartManagedOnRegister && orgOptions" not in runners
    assert "/scope" in apply
    assert "isInventoryDeviceRegistered" in util
    assert "selected_udids" in util


def test_lab_runner_playbook_is_multi_host_not_platform_usb_farm():
    doc = (ROOT / "docs" / "setup" / "managementconsole.md").read_text(encoding="utf-8")
    assert "多台设备机接入" in doc
    assert "**不要**把所有测试机插到跑 Platform" in doc
    assert "systemd" in doc
    assert "任务计划程序" in doc
    assert "网页**不能**替你启动远程电脑上的 Runner" in doc
