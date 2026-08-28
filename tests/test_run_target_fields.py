"""批跑 / 入队 / 计划共用 RunTargetFields 契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"


def test_run_target_options_shared():
    text = (FE / "composables" / "runTargetOptions.ts").read_text(encoding="utf-8")
    assert "export const PLATFORM_OPTIONS" in text
    assert 'label: "安卓"' in text
    assert 'label: "苹果"' in text
    assert "platformBadgeLabel" in (FE / "components" / "JobsPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "export const WEB_BROWSER_OPTIONS" in text
    assert "export const WEB_ENGINE_OPTIONS" in text
    assert "export const MOBILE_BACKEND_OPTIONS" in text
    assert "export function applyPlatformSideEffects" in text
    assert "export function isDevicelessPlatform" in text
    assert "export function stripDevicelessSubmitPayload" in text
    assert 'value: "http"' in text
    assert "wda_bundle" in text
    assert "parallel_workers" in text


def test_run_target_fields_component():
    text = (FE / "components" / "common" / "RunTargetFields.vue").read_text(
        encoding="utf-8"
    )
    assert "DevicePicker" in text
    assert "import ApSelect" in text
    assert "<ApSelect" in text
    assert "WEB_BROWSER_OPTIONS" in text
    assert "MOBILE_BACKEND_OPTIONS" in text
    assert "model.wda_bundle" in text
    assert "model.parallel_workers" in text
    assert "model.preferred_runner_id" in text
    assert "applyPlatformSideEffects" in text
    assert "isHttp" in text
    assert "API 环境 profile" in text


def test_run_target_fields_reused_by_job_enqueue_schedule():
    for rel in (
        "components/JobCreatePanel.vue",
        "components/design/EnqueueRunConfigCard.vue",
        "components/SchedulesPanel.vue",
    ):
        text = (FE / rel).read_text(encoding="utf-8")
        assert "RunTargetFields" in text, rel
        assert "webBrowserOptions" not in text, rel
        assert "scheduleBrowserOptions" not in text, rel

    schedules = (FE / "components" / "SchedulesPanel.vue").read_text(encoding="utf-8")
    assert "isDevicelessPlatform" in schedules
    assert "scheduleForm.platform !== 'web'" not in schedules


def test_job_create_step4_title_follows_platform():
    text = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert 'title: isDeviceless.value ? "执行节点" : "设备"' in text


def test_jobs_panel_http_badge_style():
    jobs = (FE / "components" / "JobsPanel.vue").read_text(encoding="utf-8")
    assert ".platform-mini-badge.http" in jobs
    assert ".platform-mini-badge.web" in jobs


def test_schedule_and_enqueue_send_run_target_fields():
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "S.scheduleForm.wda_bundle" in actions
    assert "S.scheduleForm.parallel_workers" in actions
    assert "isDevicelessPlatform" in actions
    assert "stripDevicelessSubmitPayload" in actions
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "backend_mode:" in panel
    assert "wda_bundle:" in panel
    assert "parallel_workers:" in panel
    state = (FE / "composables" / "mcExecState.ts").read_text(encoding="utf-8")
    assert "wda_bundle: \"\"" in state
    assert "parallel_workers: 0" in state
