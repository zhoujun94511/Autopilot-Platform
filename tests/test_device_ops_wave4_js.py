"""AUD-2026-12 Wave 4：Devices / Ops 展示纯函数与接线门禁。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
DEVICE_UTIL = FE / "utils" / "deviceDisplay.ts"
OPS_HEALTH_UTIL = FE / "utils" / "opsHealthRows.ts"
DEVICE_FILTERS = FE / "composables" / "useDeviceBoardFilters.ts"
DEVICES_PANEL = FE / "components" / "DevicesPanel.vue"
OPS_PANEL = FE / "components" / "OpsPanel.vue"


def test_device_display_util_exports():
    assert DEVICE_UTIL.is_file()
    text = DEVICE_UTIL.read_text(encoding="utf-8")
    for name in (
        "normalizePlatform",
        "platformBadgeLabel",
        "deviceKey",
        "deviceDomId",
        "udidSummary",
        "runnerSummary",
        "displayName",
        "deviceNickname",
        "deviceOsLabel",
        "deviceSourceLabel",
        "runnerSourceLabel",
        "deviceCardSummary",
        "deviceAvailability",
        "remainingLabel",
        "reservationExtraNote",
        "occupyLabel",
        "groupDevicesByPlatform",
    ):
        assert f"function {name}" in text or f"export function {name}" in text
    # 空闲态不得复用 job succeeded
    assert 'status: "ready"' in text
    assert "GENERIC_NAMES" in text
    assert 'android: "安卓"' in text
    assert 'ios: "苹果"' in text
    assert 'web: "网页"' in text
    assert 'return "接口"' in text


def test_device_board_ux_alignment():
    """设备卡 UX：ready 态、截断 Runner、详情 a11y、操作分层、标签中文。"""
    cards = (FE / "components" / "DeviceBoardCards.vue").read_text(encoding="utf-8")
    table = (FE / "components" / "DeviceBoardTable.vue").read_text(encoding="utf-8")
    status_util = (FE / "utils" / "status.ts").read_text(encoding="utf-8")
    styles = (FE / "styles.css").read_text(encoding="utf-8")

    assert 'status: "ready"' in (FE / "utils" / "deviceDisplay.ts").read_text(encoding="utf-8")
    assert 'ready: "空闲"' in status_util
    assert ".status-ready" in styles
    # iOS 平台色不得再 alias 到 claimed
    assert "--purple-soft-bg: var(--claimed-soft-bg)" not in styles

    for src in (cards, table):
        assert "platformBadgeLabel" in src
        assert "deviceAvailability" in src
        assert 'status="succeeded" label="空闲"' not in src
        assert "toUpperCase()" not in src

    assert "udidSummary" in cards
    assert "deviceNickname" in cards
    assert "deviceOsLabel" in table
    assert "复制 UDID" in cards
    assert 'meta-label">UDID' in cards
    assert 'v-if="!showPlatformSections"' in cards
    # Runner 在详情里，不当成卡片主标识
    assert "复制 Runner ID" in cards
    assert "runnerSummary" in table

    assert 'aria-expanded=' in cards
    assert "后端能力" in cards
    assert 'meta-label">backends' not in cards and "backends" not in cards.lower().split("后端能力")[0][-40:]
    assert "来源 / 所有者" not in cards  # 展开区去重
    assert "action-menu" not in cards
    assert "action-menu" not in table
    assert "停用维护" in cards
    assert "停用维护" in table
    assert "admin.copyText" in cards
    assert "deviceCardSummary" in cards
    assert "详情" in cards
    assert "占用设备" in cards
    assert 'aria-label="更多操作"' not in cards
    assert 'aria-label="更多操作"' not in table
    assert "reservationExtraNote" in cards
    assert 'v-if="d.busy && !d.busy_kind && occupyLabel(d)"' in cards
    assert '{{ d.reservation_username || "用户" }} 占用' not in cards


def test_use_device_board_filters_exists():
    assert DEVICE_FILTERS.is_file()
    text = DEVICE_FILTERS.read_text(encoding="utf-8")
    assert "useDeviceBoardFilters" in text
    assert "from \"../utils/deviceDisplay\"" in text or "from '../utils/deviceDisplay'" in text


def test_devices_panel_uses_extracted_modules():
    src = DEVICES_PANEL.read_text(encoding="utf-8")
    assert "useDeviceBoardFilters" in src
    assert "deviceDisplay" in src
    assert "DeviceBoardCards" in src
    assert "DeviceBoardTable" in src
    assert not re.search(r"\bfunction normalizePlatform\b", src)
    assert not re.search(r"\bfunction deviceKey\b", src)
    assert not re.search(r"\bfunction sourceLabel\b", src)
    assert "class=\"device-card\"" not in src
    assert "<table>" not in src


def test_devices_panel_empty_state_stays_while_filtering():
    """无设备时切筛选不得用 loading 拆掉空状态（否则区域会闪）。"""
    src = DEVICES_PANEL.read_text(encoding="utf-8")
    assert 'v-if="!items.length && hasLoaded"' in src
    assert 'v-if="!items.length && !loading"' not in src
    assert "v-else-if=\"items.length && viewMode === 'cards'\"" in src
    assert 'v-else-if="items.length"' in src
    filters = DEVICE_FILTERS.read_text(encoding="utf-8")
    assert "skipEmptyFilterReload" in filters
    assert "hasLoaded" in filters


def test_device_board_child_sfcs():
    cards = FE / "components" / "DeviceBoardCards.vue"
    table = FE / "components" / "DeviceBoardTable.vue"
    assert cards.is_file() and table.is_file()
    cards_src = cards.read_text(encoding="utf-8")
    table_src = table.read_text(encoding="utf-8")
    assert "deviceCardSummary" in cards_src
    assert "deviceSourceLabel" in table_src
    assert "onReserveDevice" in cards_src
    assert "onReserveDevice" in table_src


def test_ops_health_rows_util_and_wiring():
    assert OPS_HEALTH_UTIL.is_file()
    util = OPS_HEALTH_UTIL.read_text(encoding="utf-8")
    assert "export function buildOpsHealthRows" in util
    assert 'id: "key"' in util
    assert 'id: "rag"' in util

    panel = OPS_PANEL.read_text(encoding="utf-8")
    assert "buildOpsHealthRows" in panel
    assert "OpsHealthOverview" in panel
    assert "from \"../utils/opsHealthRows\"" in panel or "from '../utils/opsHealthRows'" in panel
    # 行装配逻辑应在 util，而非面板内联大数组
    assert panel.count('id: "key"') == 0
    assert panel.count('label: "API 密钥"') == 0
    assert '配置健康' not in panel or "OpsHealthOverview" in panel

    overview = FE / "components" / "OpsHealthOverview.vue"
    assert overview.is_file()
    ov = overview.read_text(encoding="utf-8")
    assert "配置健康" in ov
    assert "selectNav" in ov or "select-nav" in ov