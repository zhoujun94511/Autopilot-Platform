"""AI 链路 G1：设计域内嵌批跑配置（EnqueueRunConfigCard）契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"


def test_enqueue_run_config_card_exists():
    text = (FE / "components" / "design" / "EnqueueRunConfigCard.vue").read_text(
        encoding="utf-8"
    )
    assert "form.artifact_id" in text
    assert "RunTargetFields" in text
    assert "manifest_status" in text
    assert "refreshScopes" in text


def test_design_cases_panel_embeds_enqueue_config():
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "EnqueueRunConfigCard" in panel
    assert "approvedEnqueueCount" in panel
    assert "批跑配置" in panel
    assert "请先在「批跑」页选择制品" not in panel
    assert "请在下方的「批跑配置」" in panel


def test_enqueue_button_visible_on_panel():
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "enqueue-action-row" in panel
    assert "入队已通过批跑" in panel


def test_artifact_run_readiness_module():
    text = (FE / "components" / "design" / "artifactRunReadiness.ts").read_text(
        encoding="utf-8"
    )
    assert "deriveArtifactRunReadiness" in text
    assert "ideUploadSteps" in text
    assert "missingArtifact" in text


def test_design_workflow_progress_includes_run_step():
    text = (FE / "components" / "design" / "designWorkflowProgress.ts").read_text(
        encoding="utf-8"
    )
    assert '"cases" | "run"' in text or "批跑入队" in text
    assert "deriveArtifactRunReadiness" in text
    assert "runReadiness" in text


def test_workflow_bar_run_enqueue_step():
    bar = (FE / "components" / "design" / "DesignWorkflowBar.vue").read_text(
        encoding="utf-8"
    )
    assert "批跑入队" in bar
    assert "refreshScopes" in bar
    assert "artifacts" in bar
    assert "deriveDesignNextAction" in bar


def test_dashboard_run_readiness_card():
    dash = (FE / "components" / "design" / "DesignDashboardPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "run-ready-card" in dash
    assert "runReadiness" in dash
    assert "ideUploadSteps" in dash
    assert "可以远程跑了" in dash


def test_enqueue_config_ide_upload_guide_when_empty():
    card = (FE / "components" / "design" / "EnqueueRunConfigCard.vue").read_text(
        encoding="utf-8"
    )
    assert "deriveArtifactRunReadiness" in card
    assert "ide-guide" in card
    assert "filteredArtifacts.length === 0" in card
    assert "AutoPilot IDE 上传步骤" in card


def test_ide_webhook_guide_module():
    text = (FE / "components" / "design" / "ideWebhookGuide.ts").read_text(encoding="utf-8")
    assert "DEFAULT_DESIGN_WEBHOOK_URL" in text
    assert "hooks/intent" in text
    assert "通知地址" in text or "自动导入" in text
    assert "高级可选" in text or "自动导入" in text


def test_ide_webhook_guide_card_embedded():
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(encoding="utf-8")
    assert "IdeWebhookGuideCard" in panel
    card = (FE / "components" / "design" / "IdeWebhookGuideCard.vue").read_text(encoding="utf-8")
    # 自动导入属高级可选项，标题须显式标注，避免被当成日常默认路径
    assert "审核通过后自动导入" in card
    assert "高级可选" in card
    assert "openOpsConfig" in card
    # 展示运维真实配置，禁止只写死本机示例
    assert "opsConfig" in card
    assert "MC_DESIGN_WEBHOOK_URL" in card


def test_enqueue_approved_passes_web_engine_and_parses_udids():
    """设计域入队须传 web_engine，且 device_udids 按字符串解析（非数组 .map）。"""
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(encoding="utf-8")
    assert "parseUdids" in panel
    assert "web_engine" in panel
    assert "device_udids || []" not in panel
    api = (FE / "api" / "designCases.ts").read_text(encoding="utf-8")
    assert "web_engine?: string" in api
    cfg = (FE / "components" / "design" / "EnqueueRunConfigCard.vue").read_text(
        encoding="utf-8"
    )
    assert "RunTargetFields" in cfg
    fields = (FE / "components" / "common" / "RunTargetFields.vue").read_text(
        encoding="utf-8"
    )
    assert "web_engine" in fields
    assert "Playwright" in fields
    assert "backend_mode" in fields
    assert "wda_bundle" in fields
    assert "parallel_workers" in fields
    api = (FE / "api" / "designCases.ts").read_text(encoding="utf-8")
    assert "backend_mode?: string" in api
    assert "wda_bundle?: string" in api
    assert "parallel?: boolean" in api


def test_automation_lifecycle_guide_on_dashboard():
    dash = (FE / "components" / "design" / "DesignDashboardPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "verify-lifecycle-card" in dash
    assert "SOLIDIFY_CLI_STEPS" in dash
    assert "VERIFIER_LIFECYCLE_STEPS" in dash


def test_ops_design_webhook_helper():
    cfg = (FE / "api" / "opsConfig.ts").read_text(encoding="utf-8")
    assert "hooks/intent" in cfg
    assert "设计域回调" in cfg or "MC_DESIGN_WEBHOOK_URL" in cfg
    ops = (FE / "components" / "OpsPanel.vue").read_text(encoding="utf-8")
    assert "design-webhook-foot" in ops
    assert "通知地址" in ops

def test_automation_status_hints_and_verifier_filter():
    hints = (FE / "components" / "design" / "automationStatusHints.ts").read_text(
        encoding="utf-8"
    )
    assert "PENDING_VERIFY" in hints
    assert "AUTOMATION_QUICK_FILTERS" in hints
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "automationFilter" in panel
    assert "verify-banner" in panel
    assert "filter-chips" in panel
    sel = (FE / "components" / "design" / "AutomationStatusSelect.vue").read_text(
        encoding="utf-8"
    )
    assert "automationStatusHint" in sel
