"""管理台下拉统一走 ApSelect：禁止原生 <select>，避免系统弹层与主题不一致。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
AP_SELECT = FE / "components" / "common" / "ApSelect.vue"
STYLES = FE / "styles.css"

NATIVE_SELECT = re.compile(r"<select[\s>]", re.I)
CREATE_SELECT = re.compile(r"""createElement\(\s*['"]select['"]\s*\)""", re.I)
# 选择器里的原生 select（避开 user-select / .ap-select / file-selector）
NATIVE_SELECT_CSS = re.compile(r"(?:^|[\s,{>+~])select(?:\s*[,:{]|\s+)", re.M)

MUST_USE_AP_SELECT = [
    "components/projects/ProjectSelect.vue",
    "components/projects/OrgSelect.vue",
    "components/common/DataPager.vue",
    "components/design/AutomationStatusSelect.vue",
    "components/JobCreatePanel.vue",
    "components/SchedulesPanel.vue",
    "components/common/RunTargetFields.vue",
    "components/ReportsPanel.vue",
    "components/AppBuildsPanel.vue",
    "components/OpsPanel.vue",
    "components/SharePanel.vue",
    "components/UsersPanel.vue",
    "components/projects/ProjectInviteCard.vue",
    "components/projects/ProjectWorkspace.vue",
    "components/projects/OrgSettingsSection.vue",
    "components/design/DesignChatPanel.vue",
    "components/design/DesignChatComposer.vue",
    "components/design/DesignCasesPanel.vue",
    "components/design/DesignDocsPanel.vue",
    "components/design/DesignCaseGenerateCard.vue",
    "components/design/EnqueueRunConfigCard.vue",
    "components/design/CaseEditDrawer.vue",
    "components/design/KnowledgeListCard.vue",
    "components/design/KnowledgeCreateForm.vue",
    "components/design/KnowledgeEditForm.vue",
    "components/design/KnowledgeImportCard.vue",
    "components/design/DocsListCard.vue",
    "components/design/DocsImportCard.vue",
    "components/design/ReqsListCard.vue",
    "components/design/ReqEditForm.vue",
    "components/remote/RemoteDeviceLogPanel.vue",
    "components/remote/files/RemoteFileIosAppSelector.vue",
]


def _iter_src_files(*suffixes: str):
    for path in FE.rglob("*"):
        if path.is_file() and path.suffix in suffixes:
            yield path


def _rel(path: Path) -> str:
    return path.relative_to(FE).as_posix()


def test_ap_select_component_contract():
    src = AP_SELECT.read_text(encoding="utf-8")
    assert 'class="ap-select"' in src
    assert 'class="ap-select-trigger"' in src
    assert 'type="button"' in src
    assert 'role="listbox"' in src
    assert 'role="option"' in src
    assert 'aria-haspopup="listbox"' in src
    assert "<Teleport" in src
    assert 'to="body"' in src
    assert "update:modelValue" in src
    assert "emit(\"change\"" in src or "emit('change'" in src
    assert "ArrowDown" in src
    assert "Escape" in src
    assert "Enter" in src
    assert 'size?: "default" | "compact" | "toolbar"' in src
    assert "var(--input-bg)" in src
    assert "var(--surface-elevated)" in src
    assert "var(--text)" in src
    assert "position: fixed" in src
    assert NATIVE_SELECT.search(src) is None
    assert "<select" not in src


def test_ap_select_display_label_mirrors_component():
    """与 ApSelect displayLabel 同算法的纯 Python 对照（无 DOM）。"""

    def display_label(model_value: str, options: list[dict], placeholder: str | None = None) -> str:
        selected = next((o for o in options if o["value"] == model_value), None)
        if selected:
            return selected["label"]
        if placeholder:
            return placeholder
        empty = next((o for o in options if o["value"] == "" and not o.get("disabled")), None)
        return empty["label"] if empty else "请选择"

    opts = [
        {"value": "", "label": "全部"},
        {"value": "web", "label": "Web"},
        {"value": "android", "label": "Android", "disabled": True},
    ]
    assert display_label("web", opts) == "Web"
    assert display_label("", opts) == "全部"
    assert display_label("missing", opts) == "全部"
    assert display_label("missing", opts, placeholder="请选择平台") == "请选择平台"
    assert display_label("x", [{"value": "a", "label": "A"}]) == "请选择"


def test_vue_and_html_do_not_use_native_select():
    offenders: list[str] = []
    for path in _iter_src_files(".vue", ".html"):
        text = path.read_text(encoding="utf-8")
        if NATIVE_SELECT.search(text):
            offenders.append(_rel(path))
    assert offenders == [], "原生 <select> 应改为 ApSelect：\n" + "\n".join(offenders)


def test_frontend_does_not_create_native_select_dom():
    offenders: list[str] = []
    for path in _iter_src_files(".vue", ".ts", ".js"):
        text = path.read_text(encoding="utf-8")
        if CREATE_SELECT.search(text):
            offenders.append(_rel(path))
    assert offenders == [], "禁止 createElement('select')：\n" + "\n".join(offenders)


def test_required_call_sites_use_ap_select():
    missing: list[str] = []
    for rel in MUST_USE_AP_SELECT:
        path = FE / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        if "import ApSelect" not in text or "<ApSelect" not in text:
            missing.append(rel)
    assert missing == [], "这些页面必须使用 ApSelect：\n" + "\n".join(missing)


def test_ap_select_importers_render_the_component():
    """引入了组件就必须在模板里渲染，避免只 import 不用。"""
    unused: list[str] = []
    for path in _iter_src_files(".vue"):
        if path == AP_SELECT:
            continue
        text = path.read_text(encoding="utf-8")
        if "import ApSelect" in text and "<ApSelect" not in text:
            unused.append(_rel(path))
    assert unused == []


def test_header_project_org_filters_use_ap_select():
    project = (FE / "components" / "projects" / "ProjectSelect.vue").read_text(encoding="utf-8")
    org = (FE / "components" / "projects" / "OrgSelect.vue").read_text(encoding="utf-8")
    assert "selectProject" in project
    assert "selectOrg" in org
    assert 'aria-label="当前项目"' in project
    assert 'aria-label="当前组织"' in org
    assert NATIVE_SELECT.search(project) is None
    assert NATIVE_SELECT.search(org) is None


def test_data_pager_page_size_uses_ap_select():
    pager = (FE / "components" / "common" / "DataPager.vue").read_text(encoding="utf-8")
    assert "pageSizeOptions" in pager
    assert 'aria-label="每页条数"' in pager
    assert "onPageSize" in pager


def test_global_css_does_not_style_native_select():
    css = STYLES.read_text(encoding="utf-8")
    assert NATIVE_SELECT_CSS.search(css) is None, "styles.css 不得再把原生 select 当表单控件"
    assert "select:focus" not in css
    assert "[data-theme=\"dark\"] select" not in css
    assert ".toolbar-select.ap-select" in css
    assert ".list-pager-size .ap-select" in css


def test_toolbar_select_class_is_only_on_ap_select():
    """toolbar-select 是旧 native select 的 class，现在只能挂在 ApSelect 上。"""
    offenders: list[str] = []
    for path in _iter_src_files(".vue"):
        text = path.read_text(encoding="utf-8")
        if 'class="toolbar-select"' not in text and "class='toolbar-select'" not in text:
            continue
        if "<ApSelect" not in text or "toolbar-select" not in text:
            offenders.append(_rel(path))
            continue
        for m in re.finditer(r"<([A-Za-z][\w.-]*)([^>]*)>", text):
            tag, attrs = m.group(1), m.group(2)
            if "toolbar-select" in attrs and tag not in ("ApSelect",):
                offenders.append(f"{_rel(path)} <{tag}>")
    assert offenders == []
