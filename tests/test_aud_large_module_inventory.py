"""AUD-2026-12 / 17：巨型模块拆分延期 — ADR 与路径基线。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDE_ROOT = ROOT.parent / "AutoPilot"
ADR = ROOT / "docs" / "architecture" / "ADR_large_module_split.md"

PLATFORM_GIANTS = (
    "autopilot_platform/frontend/src/components/design/DesignChatPanel.vue",
    "autopilot_platform/frontend/src/components/OpsPanel.vue",
    "autopilot_platform/frontend/src/components/DevicesPanel.vue",
    "autopilot_platform/frontend/src/components/design/DesignCasesPanel.vue",
    "autopilot_platform/frontend/src/App.vue",
    "autopilot_platform/frontend/src/components/JobCreatePanel.vue",
    "autopilot_platform/frontend/src/components/ReportsPanel.vue",
)

IDE_GIANTS = (
    "autopilot/ui/main_window/mgmt.py",
    "autopilot/ui/main_window/mgmt_session.py",
    "autopilot/ui/main_window/mgmt_runner_web.py",
    "autopilot/ui/main_window/mgmt_delivery.py",
    "autopilot/ui/main_window/mgmt_errors.py",
)


def test_adr_large_module_split_deferred():
    assert ADR.is_file()
    text = ADR.read_text(encoding="utf-8")
    assert "AUD-2026-12" in text
    assert "AUD-2026-17" in text
    assert "DEFERRED" in text
    assert "DesignChatPanel.vue" in text
    assert "mgmt.py" in text
    assert "mgmt_delivery.py" in text
    assert "mgmt_session.py" in text
    assert "mgmt_runner_web.py" in text
    assert "useDesignChatFab" in text or "chatFabPosition" in text
    assert "DesignChatMessages" in text or "DesignChatComposer" in text
    assert "DesignChatSessionList" in text
    assert "Wave" in text
    assert "deviceDisplay" in text or "useDeviceBoardFilters" in text
    assert "opsHealthRows" in text
    assert "DeviceBoardCards" in text or "OpsHealthOverview" in text


def test_documented_platform_giants_exist():
    missing = [rel for rel in PLATFORM_GIANTS if not (ROOT / rel).is_file()]
    assert not missing, f"ADR 清单路径缺失（改名须同步 ADR）: {missing}"


def test_documented_ide_giants_exist_when_sibling_checkout():
    if not IDE_ROOT.is_dir():
        return
    missing = [rel for rel in IDE_GIANTS if not (IDE_ROOT / rel).is_file()]
    assert not missing, f"IDE 巨型模块路径缺失: {missing}"
