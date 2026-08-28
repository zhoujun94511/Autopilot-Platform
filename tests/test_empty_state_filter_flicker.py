"""空列表切筛选时，不得用 loading 拆掉空状态 / 闪出分页条。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"

PAGED = FE / "composables" / "usePagedList.ts"
PAGER = FE / "components" / "common" / "DataPager.vue"

PANELS = [
    FE / "components" / "JobsPanel.vue",
    FE / "components" / "ReportsPanel.vue",
    FE / "components" / "SchedulesPanel.vue",
    FE / "components" / "ArtifactsPanel.vue",
    FE / "components" / "RunnersPanel.vue",
    FE / "components" / "AuditPanel.vue",
    FE / "components" / "UsersPanel.vue",
    FE / "components" / "DevicesPanel.vue",
    FE / "components" / "design" / "DesignCasesPanel.vue",
]


def test_paged_list_tracks_loaded_and_empty_universe():
    src = PAGED.read_text(encoding="utf-8")
    assert "hasLoaded" in src
    assert "universeEmpty" in src
    assert "filterSources" in src
    assert "isUnfiltered" in src
    assert "skipEmptyFilterReload" in src


def test_data_pager_hides_when_total_is_zero():
    src = PAGER.read_text(encoding="utf-8")
    assert "mode === 'page' && multiPage" in src
    assert "total > 0 || loading" not in src


def test_list_panels_keep_empty_state_while_filtering():
    for path in PANELS:
        src = path.read_text(encoding="utf-8")
        assert "hasLoaded" in src, path.name
        assert "!items.length && !loading" not in src, path.name
        assert "!rows.length && !loading" not in src, path.name
        assert "!cases.length && !loading" not in src, path.name
        assert "v-if=\"total > 0 || loading\"" not in src, path.name


def test_jobs_and_reports_skip_filter_reload_when_universe_empty():
    jobs = (FE / "components" / "JobsPanel.vue").read_text(encoding="utf-8")
    assert "filterSources: [statusFilter]" in jobs
    assert "isUnfiltered:" in jobs
    reports = (FE / "components" / "ReportsPanel.vue").read_text(encoding="utf-8")
    assert "filterSources:" in reports
    assert "isUnfiltered:" in reports
    builds = (FE / "components" / "AppBuildsPanel.vue").read_text(encoding="utf-8")
    assert "filterSources: [platformFilter]" in builds
