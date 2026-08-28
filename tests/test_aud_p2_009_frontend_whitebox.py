"""前端 Router/Pinia/runtime 接线白盒：整改链路契约。

覆盖模块：
- router/tabs.ts（Tab ↔ path 目录、legacy 重定向、hub/ops query）
- navigation/tabSync.ts（双向同步、ops 深链）
- router/guards.ts（登录后 ops/manageUsers 门禁）
- mcShellState + useShellStore（pageVisible / openOpsConfig）
- mcRefreshScopes（pageVisible 停轮询、design 空 scopes）
- composables/platformRuntime.ts runtime（仅 wire；useMcStore.ts 可为 re-export shim）
- main.ts / app.py SPA catch-all（含深链运行时）
- Panel 直连 Pinia（禁止业务再 import useMcStore）
- openOpsConfig / consumeOpsFocusCategory / 项目过滤防抖行为镜像
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
APP_PY = ROOT / "autopilot_platform" / "platform" / "app.py"


# —— 纯逻辑镜像（与 tabs.ts / mcRefreshScopes.ts 对齐）——

LEGACY_TAB_REDIRECT = {
    "design-chat": "dashboard",
    "design-config": "ops",
}

TAB_PATHS = {
    "dashboard": "/dashboard",
    "projects": "/projects",
    "share": "/share",
    "design-dashboard": "/design",
    "design-docs": "/design/docs",
    "design-cases": "/design/cases",
    "design-knowledge": "/design/knowledge",
    "artifacts": "/exec/artifacts",
    "app-builds": "/exec/app-builds",
    "jobs": "/exec/jobs",
    "schedules": "/exec/schedules",
    "reports": "/exec/reports",
    "devices": "/infra/devices",
    "ops": "/admin/ops",
    "audit": "/admin/audit",
    "users": "/admin/users",
}


def normalize_tab_id(raw: str) -> str:
    t = (raw or "").strip()
    if t in LEGACY_TAB_REDIRECT:
        return LEGACY_TAB_REDIRECT[t]
    if t in TAB_PATHS:
        return t
    return "dashboard"


def path_for_tab(tab: str) -> str:
    return TAB_PATHS.get(normalize_tab_id(tab), "/dashboard")


def tab_from_path(path: str) -> str:
    p = (path or "/").rstrip("/") or "/"
    if p in ("/", ""):
        return "dashboard"
    by_path = {v: k for k, v in TAB_PATHS.items()}
    if p in by_path:
        return by_path[p]
    best_tab = None
    best_len = -1
    for tab, path in TAB_PATHS.items():
        if p == path or p.startswith(path + "/"):
            if len(path) > best_len:
                best_len = len(path)
                best_tab = tab
    return best_tab or "dashboard"


def hub_section_from_query(section: str, tab: str) -> str:
    s = (section or "").strip()
    if tab == "devices":
        return s if s in ("pools", "runners", "devices") else "devices"
    if tab == "projects":
        return s if s in ("org", "collab") else ""
    return ""


def poll_interval_for_tab(
    tab: str, *, has_active_jobs: bool = False, page_visible: bool = True
) -> int | None:
    if not page_visible:
        return None
    base = {
        "dashboard": 30_000,
        "devices": 20_000,
        "jobs": 15_000,
        "schedules": 60_000,
        "ops": 60_000,
    }.get(tab)
    if base is None:
        return None
    if tab == "jobs":
        return 10_000 if has_active_jobs else 45_000
    if tab == "dashboard" and has_active_jobs:
        return 15_000
    return base


def route_guard_redirect(
    *,
    logged_in: bool,
    is_platform_admin: bool,
    can_manage_users: bool,
    guards: list[str],
    guest: bool = False,
) -> str | None:
    """镜像 router/guards.ts：未登录放行深链；登录后拦 ops/manageUsers。"""
    if guest:
        return None
    if not logged_in:
        return None
    if "ops" in guards and not is_platform_admin:
        return path_for_tab("dashboard")
    if "manageUsers" in guards and not can_manage_users:
        return path_for_tab("dashboard")
    return None


# —— 场景矩阵 ——


@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        ("dashboard", "dashboard"),
        ("design-chat", "dashboard"),
        ("design-config", "ops"),
        ("nope", "dashboard"),
        ("", "dashboard"),
        ("jobs", "jobs"),
    ],
)
def test_normalize_tab_id_matrix(raw: str, expect: str):
    assert normalize_tab_id(raw) == expect


@pytest.mark.parametrize(
    ("path", "expect"),
    [
        ("/", "dashboard"),
        ("/dashboard", "dashboard"),
        ("/design/docs", "design-docs"),
        ("/design/docs/extra", "design-docs"),
        ("/exec/jobs", "jobs"),
        ("/admin/ops", "ops"),
        ("/unknown", "dashboard"),
    ],
)
def test_tab_from_path_prefix(path: str, expect: str):
    assert tab_from_path(path) == expect


@pytest.mark.parametrize(
    ("tab", "section", "expect"),
    [
        ("devices", "pools", "pools"),
        ("devices", "bad", "devices"),
        ("projects", "org", "org"),
        ("projects", "", ""),
        ("jobs", "x", ""),
    ],
)
def test_hub_section_matrix(tab: str, section: str, expect: str):
    assert hub_section_from_query(section, tab) == expect


@pytest.mark.parametrize(
    ("tab", "visible", "active", "expect"),
    [
        ("jobs", False, True, None),
        ("jobs", True, True, 10_000),
        ("jobs", True, False, 45_000),
        ("dashboard", True, True, 15_000),
        ("projects", True, False, None),
        ("design-cases", True, False, None),
    ],
)
def test_poll_interval_page_visible_chain(
    tab: str, visible: bool, active: bool, expect: int | None
):
    assert (
        poll_interval_for_tab(tab, has_active_jobs=active, page_visible=visible) == expect
    )


@pytest.mark.parametrize(
    ("logged_in", "admin", "manage", "guards", "expect"),
    [
        (False, False, False, ["ops"], None),
        (True, False, False, ["ops"], "/dashboard"),
        (True, True, False, ["ops"], None),
        (True, False, False, ["manageUsers"], "/dashboard"),
        (True, False, True, ["manageUsers"], None),
        (True, False, False, ["auth"], None),
    ],
)
def test_route_guard_chain(logged_in, admin, manage, guards, expect):
    assert (
        route_guard_redirect(
            logged_in=logged_in,
            is_platform_admin=admin,
            can_manage_users=manage,
            guards=guards,
        )
        == expect
    )


# —— 源码契约：目录 / 同步 / 门禁 ——


def test_tabs_ts_catalog_covers_all_paths():
    text = (FE / "router" / "tabs.ts").read_text(encoding="utf-8")
    for tab, path in TAB_PATHS.items():
        assert f'tab: "{tab}"' in text or f"tab: '{tab}'" in text, tab
        assert f'path: "{path}"' in text, path
    assert 'LEGACY_TAB_REDIRECT' in text
    assert '"design-chat": "dashboard"' in text
    assert '"design-config": "ops"' in text
    assert "hubSectionFromQuery" in text
    assert "opsCategoryFromQuery" in text


def test_tab_sync_bidirectional_and_ops_deeplink():
    text = (FE / "navigation" / "tabSync.ts").read_text(encoding="utf-8")
    assert "export function installTabRouteSync" in text
    assert "export function applyTabFromRoute" in text
    assert "export function goToOpsCategory" in text
    assert "router.afterEach" in text
    assert "watch(" in text
    assert 'path: "/admin/ops"' in text
    assert "query: { category: cat }" in text
    assert "suppressRoutePush" in text


def test_route_guards_source_matches_mirror():
    text = (FE / "router" / "guards.ts").read_text(encoding="utf-8")
    assert "useAuthStore" in text
    assert 'guards.includes("ops")' in text
    assert "!auth.isPlatformAdmin" in text
    assert 'guards.includes("manageUsers")' in text
    assert "!auth.canManageUsers" in text
    assert "if (!auth.loggedIn) return true" in text


def test_router_index_wires_lazy_panels_and_guards_meta():
    text = (FE / "router" / "index.ts").read_text(encoding="utf-8")
    assert "TAB_PANEL_LOADERS" in text
    assert "createWebHistory" in text
    assert "meta: {" in text
    assert "guards: def.guards" in text


# —— Shell / Polling / Runtime ——


def test_mc_shell_state_owns_page_visible_and_ops_gate():
    text = (FE / "composables" / "mcShellState.ts").read_text(encoding="utf-8")
    assert "export const pageVisible" in text
    assert "export function openOpsConfig" in text
    assert "isPlatformAdmin" in text
    assert "goToOpsCategory" in text
    assert "export function consumeOpsFocusCategory" in text
    fn = re.search(r"export function openOpsConfig\([\s\S]*?\n}", text)
    assert fn, "openOpsConfig missing"
    body = fn.group(0)
    assert "if (!isPlatformAdmin" in body
    assert 'activeTab.value = "ops"' in body or "activeTab.value = 'ops'" in body


def test_shell_store_exports_page_visible_and_polling():
    text = (FE / "stores" / "shellStore.ts").read_text(encoding="utf-8")
    assert "pageVisible: Shell.pageVisible" in text
    assert "setPageVisible: Polling.setPageVisible" in text
    assert "refreshForTab" in text


def test_polling_installs_active_tab_watcher_and_visibility():
    text = (FE / "composables" / "mcPolling.ts").read_text(encoding="utf-8")
    assert "export function installActiveTabWatcher" in text
    assert "export function setPageVisible" in text
    assert "export function setOverlayBusy" in text
    assert "overlayBusy" in text
    assert "export function onActiveTabChanged" in text
    assert "pageVisible" in text


def test_projects_install_filter_watcher():
    text = (FE / "composables" / "mcProjectsActions.ts").read_text(encoding="utf-8")
    assert "export function installProjectFilterWatcher" in text
    assert "persistProjectId" in text
    assert "400" in text  # debounce ms


def test_runtime_is_wire_only_no_facade():
    text = (FE / "composables" / "platformRuntime.ts").read_text(encoding="utf-8")
    assert "export function wirePlatformRuntime" in text
    assert "wireMcStoreToRouter" in text
    assert "installTabRouteSync" in text
    assert "installProjectFilterWatcher" in text
    assert "installActiveTabWatcher" in text
    assert "export function useMcStore(" not in text
    assert "reactive({" not in text
    # 触达各域 Pinia，避免未注册
    for name in (
        "useAuthStore",
        "useShellStore",
        "useExecStore",
        "useAdminStore",
        "useOpsStore",
        "useProjectsStore",
        "useContextStore",
    ):
        assert name in text, name


def test_main_wires_router_and_guards():
    text = (FE / "main.ts").read_text(encoding="utf-8")
    assert "wirePlatformRuntime(router)" in text
    assert "installRouteGuards(router)" in text
    assert "app.use(pinia)" in text
    assert "app.use(router)" in text


def test_spa_fallback_in_platform_app():
    text = APP_PY.read_text(encoding="utf-8")
    assert "AUD-P2-009" in text
    assert 'full_path:path' in text or "full_path:path" in text
    assert "_SPA_SKIP_PREFIXES" in text
    assert "index.html" in text
    assert "_SPA_HTML_HEADERS" in text
    assert "no-cache" in text
    assert "MC_FRONTEND_DEV_URL" in text
    assert "RedirectResponse" in text
    for skip in ("api", "health", "metrics", "assets", "docs", "openapi"):
        assert skip in text, skip


def test_no_business_panel_imports_use_mc_store():
    """业务 Panel/App 不得再依赖 useMcStore 门面。"""
    offenders: list[str] = []
    paths = list(FE.rglob("*.vue")) + list(FE.rglob("*.ts"))
    for path in sorted(paths):
        if path.name in ("useMcStore.ts", "platformRuntime.ts", "main.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"""from\s+['\"].*useMcStore['\"]""", text):
            offenders.append(str(path.relative_to(FE)))
        if re.search(r"\buseMcStore\s*\(", text):
            offenders.append(str(path.relative_to(FE)))
    assert not offenders, "仍依赖 useMcStore：" + "; ".join(sorted(set(offenders)))


def test_app_vue_uses_pinia_not_mc_store():
    text = (FE / "App.vue").read_text(encoding="utf-8")
    assert "useAuthStore" in text
    assert "useShellStore" in text
    assert "from \"./composables/useMcStore\"" not in text
    assert "from './composables/useMcStore'" not in text
    assert "setPageVisible" in text
    assert "guardAdminTabs" in text
    assert "platformRoleLabel" in text
    assert "showShareNav" in text
    assert "showDevicesNav" in text
    assert "loggedIn" in text


def test_pinia_stores_share_mc_state_refs():
    """单一真源：各 store 必须引用 mc*State，而非本地镜像。"""
    checks = {
        "stores/auth.ts": "mcSessionState",
        "stores/shellStore.ts": "mcShellState",
        "stores/execution.ts": "mcExecState",
        "stores/adminStore.ts": "mcAdminState",
        "stores/opsStore.ts": "mcOpsState",
        "stores/projectsStore.ts": "mcProjectsState",
    }
    for rel, state_mod in checks.items():
        text = (FE / rel).read_text(encoding="utf-8")
        assert state_mod in text, rel
        assert "defineStore" in text, rel


def test_session_actions_own_bootstrap_and_apply_auth():
    """会话动作从 useMcStore 迁出后，鉴权时序契约落在 mcSessionActions。"""
    text = (FE / "composables" / "mcSessionActions.ts").read_text(encoding="utf-8")
    assert "beginAuthSession" in text
    apply = re.search(r"export async function applyAuthSession\([\s\S]*?\n}", text)
    assert apply, "applyAuthSession missing"
    body = apply.group(0)
    assert "beginAuthSession" in body
    assert body.index("beginAuthSession") < body.index("saveJwt")

    boot = re.search(r"export async function bootstrap\(\) \{.*?^}", text, re.M | re.S)
    assert boot, "bootstrap missing"
    bbody = boot.group(0)
    assert "ensureFreshSession" in bbody
    assert bbody.index("ensureFreshSession") < bbody.index("refreshForTab")


def test_use_mc_store_no_capability_exports():
    """能力档仅 useCapabilities；platformRuntime 不得再导出能力字段。"""
    text = (FE / "composables" / "platformRuntime.ts").read_text(encoding="utf-8")
    for key in (
        "canEditProject",
        "canManageProject",
        "isProjectViewer",
        "canViewProject",
        "canOps",
        "canManageOrg",
        "currentProjectRole",
    ):
        assert key not in text, f"runtime 仍提及能力档 {key}"


def test_refresh_scopes_source_aligns_with_poll_mirror():
    text = (FE / "composables" / "mcRefreshScopes.ts").read_text(encoding="utf-8")
    assert "if (opts.pageVisible === false) return null" in text
    assert '"design-dashboard": []' in text
    assert 'tab.startsWith("design-")' in text


# —— 行为镜像：ops 深链 / 项目过滤 / Tab guards ——


@dataclass
class ShellNavState:
    active_tab: str = "dashboard"
    ops_focus_category: str = ""
    notified: list[str] = field(default_factory=list)


def open_ops_config(
    state: ShellNavState,
    *,
    is_platform_admin: bool,
    category: str = "ai_model",
    has_router: bool = False,
) -> dict | None:
    """镜像 mcShellState.openOpsConfig（无 router 时本地写 tab；有 router 时走 goToOpsCategory）。"""
    if not is_platform_admin:
        state.notified.append("需由平台管理员在「运维」中配置")
        return None
    if has_router:
        # goToOpsCategory：trim 后写入
        cat = (category or "ai_model").strip() or "ai_model"
        state.ops_focus_category = cat
        state.active_tab = "ops"
        return {"path": "/admin/ops", "query": {"category": cat}}
    # 无 router：与源码一致，不 trim
    state.ops_focus_category = category or "ai_model"
    state.active_tab = "ops"
    return None


def consume_ops_focus_category(state: ShellNavState) -> str:
    v = (state.ops_focus_category or "").strip()
    state.ops_focus_category = ""
    return v


@pytest.mark.parametrize(
    ("admin", "category", "expect_tab", "expect_cat", "expect_notify"),
    [
        (False, "ai_model", "dashboard", "", True),
        (True, "ai_model", "ops", "ai_model", False),
        (True, "", "ops", "ai_model", False),
        (True, "  webhook  ", "ops", "  webhook  ", False),  # 无 router 不 trim
    ],
)
def test_open_ops_config_behavior_no_router(
    admin: bool, category: str, expect_tab: str, expect_cat: str, expect_notify: bool
):
    st = ShellNavState()
    route = open_ops_config(st, is_platform_admin=admin, category=category, has_router=False)
    assert route is None
    assert st.active_tab == expect_tab
    assert st.ops_focus_category == expect_cat
    assert bool(st.notified) is expect_notify


def test_open_ops_config_with_router_pushes_ops_query():
    st = ShellNavState(active_tab="jobs")
    route = open_ops_config(
        st, is_platform_admin=True, category="  ai_model  ", has_router=True
    )
    assert route == {"path": "/admin/ops", "query": {"category": "ai_model"}}
    assert st.active_tab == "ops"
    assert st.ops_focus_category == "ai_model"


def test_consume_ops_focus_category_clears():
    st = ShellNavState(ops_focus_category=" webhook ")
    assert consume_ops_focus_category(st) == "webhook"
    assert st.ops_focus_category == ""
    assert consume_ops_focus_category(st) == ""


@dataclass
class ProjectFilterEvent:
    persisted: list[str] = field(default_factory=list)
    refreshed_tabs: list[str] = field(default_factory=list)


def on_project_filter_changed(
    ev: ProjectFilterEvent,
    *,
    project_id: str,
    logged_in: bool,
    active_tab: str,
    fire_debounce: bool = True,
) -> None:
    """镜像 installProjectFilterWatcher 回调（防抖后执行段）。"""
    ev.persisted.append(str(project_id or ""))
    if not logged_in:
        return
    if fire_debounce:
        ev.refreshed_tabs.append(active_tab)


def test_project_filter_watcher_skips_refresh_when_logged_out():
    ev = ProjectFilterEvent()
    on_project_filter_changed(
        ev, project_id="p1", logged_in=False, active_tab="jobs"
    )
    assert ev.persisted == ["p1"]
    assert ev.refreshed_tabs == []


def test_project_filter_watcher_refreshes_active_tab_when_logged_in():
    ev = ProjectFilterEvent()
    on_project_filter_changed(
        ev, project_id="p2", logged_in=True, active_tab="artifacts"
    )
    assert ev.persisted == ["p2"]
    assert ev.refreshed_tabs == ["artifacts"]


def test_project_filter_watcher_source_debounce_and_gate():
    text = (FE / "composables" / "mcProjectsActions.ts").read_text(encoding="utf-8")
    start = text.find("export function installProjectFilterWatcher")
    assert start >= 0, "installProjectFilterWatcher missing"
    body = text[start : start + 700]
    assert "persistProjectId" in body
    assert "if (!opts.loggedIn.value) return" in body
    assert "refreshForTab" in body
    assert "400" in body


def _parse_tab_guards_from_source() -> dict[str, list[str]]:
    text = (FE / "router" / "tabs.ts").read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for m in re.finditer(
        r'tab:\s*"([^"]+)"[\s\S]*?guards:\s*\[([^]]*)]',
        text,
    ):
        tab = m.group(1)
        guards = re.findall(r'"([^"]+)"', m.group(2))
        out[tab] = guards
    return out


def test_tab_route_guards_matrix_from_source():
    guards = _parse_tab_guards_from_source()
    assert set(guards) == set(TAB_PATHS)
    assert guards["ops"] == ["auth", "ops"]
    assert guards["audit"] == ["auth", "manageUsers"]
    assert guards["users"] == ["auth", "manageUsers"]
    for tab, g in guards.items():
        assert "auth" in g, tab
        if tab not in ("ops", "audit", "users"):
            assert g == ["auth"], tab


MAIN_PANELS_REQUIRE_PINIA = {
    "components/DashboardPanel.vue": ("useExecStore", "useShellStore"),
    "components/JobsPanel.vue": ("useExecStore",),
    "components/ArtifactsPanel.vue": ("useExecStore",),
    "components/AppBuildsPanel.vue": ("useExecStore",),
    "components/SchedulesPanel.vue": ("useExecStore",),
    "components/ReportsPanel.vue": ("useExecStore",),
    "components/DevicesPanel.vue": ("useExecStore", "useShellStore"),
    "components/RunnersPanel.vue": ("useExecStore",),
    "components/OpsPanel.vue": ("useOpsStore", "useShellStore"),
    "components/ProjectsPanel.vue": ("useProjectsStore",),
    "components/SharePanel.vue": ("useOpsStore",),
    "components/AuditPanel.vue": ("useAdminStore",),
    "components/UsersPanel.vue": ("useAdminStore",),
    "components/design/DesignCasesPanel.vue": ("useExecStore", "useShellStore"),
    "components/design/DesignDocsPanel.vue": ("useShellStore", "useProjectsStore"),
    "components/design/DesignKnowledgePanel.vue": ("useShellStore", "useProjectsStore"),
    "components/design/DesignDashboardPanel.vue": ("useShellStore", "useProjectsStore"),
}


def test_main_panels_positively_wire_pinia_stores():
    for rel, stores in MAIN_PANELS_REQUIRE_PINIA.items():
        text = (FE / rel).read_text(encoding="utf-8")
        for banned in (
            'from "./composables/useMcStore"',
            "from './composables/useMcStore'",
            'from "../composables/useMcStore"',
            "from '../composables/useMcStore'",
            'from "../../composables/useMcStore"',
            "from '../../composables/useMcStore'",
        ):
            assert banned not in text, rel
        for store in stores:
            assert store in text, f"{rel} missing {store}"


# —— SPA History 深链运行时 ——


@pytest.fixture()
def spa_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from autopilot_platform.platform.app import create_app
    from autopilot_platform.platform.core.db import reset_engine

    dist = ROOT / "autopilot_platform" / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        pytest.skip("Vue dist missing; run: cd autopilot_platform/frontend && npm run build")

    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.delenv("MC_FRONTEND_DEV_URL", raising=False)
    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'spa.db').as_posix()}")
    with TestClient(app) as c:
        yield c
    reset_engine()


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/exec/jobs",
        "/admin/ops",
        "/admin/ops?category=ai_model",
        "/infra/devices?section=runners",
        "/design/cases",
        "/projects?section=org",
    ],
)
def test_spa_deeplink_serves_index_html(spa_client, path: str):
    r = spa_client.get(path)
    assert r.status_code == 200, path
    ctype = r.headers.get("content-type", "")
    assert "text/html" in ctype
    cache = (r.headers.get("cache-control") or "").lower()
    assert "no-cache" in cache or "no-store" in cache
    body = r.text
    assert "<!DOCTYPE html>" in body or "<html" in body.lower()
    assert "/assets/" in body


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/bootstrap",
        "/health",
    ],
)
def test_spa_does_not_swallow_api_or_health(spa_client, path: str):
    r = spa_client.get(path)
    assert r.status_code == 200, path
    ctype = r.headers.get("content-type", "")
    assert "application/json" in ctype or "json" in ctype
    # 不得回落到 SPA index
    assert "/assets/" not in r.text


def test_spa_unknown_api_prefix_still_404_not_index(spa_client):
    r = spa_client.get("/api/v1/__no_such_endpoint__")
    assert r.status_code in (404, 405, 401, 403)
    if "text/html" in r.headers.get("content-type", ""):
        assert "/assets/" not in r.text


def test_dev_frontend_redirects_to_vite_not_stale_dist(tmp_path, monkeypatch):
    """联调时 :8000 不得再吐 hashed dist，否则 IDE 会 404 已删除的 CSS。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from autopilot_platform.platform.app import create_app
    from autopilot_platform.platform.core.db import reset_engine

    monkeypatch.setenv("MC_FRONTEND_DEV_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.delenv("MC_ENV", raising=False)
    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'devspa.db').as_posix()}")
    try:
        with TestClient(app) as c:
            r = c.get("/", follow_redirects=False)
            assert r.status_code == 307
            assert r.headers.get("location", "").startswith("http://127.0.0.1:5173")
            deep = c.get("/dashboard", follow_redirects=False)
            assert deep.status_code == 307
            assert deep.headers.get("location") == "http://127.0.0.1:5173/dashboard"
            api = c.get("/health")
            assert api.status_code == 200
            stale = c.get("/assets/index-_mUEbnPf.js", follow_redirects=False)
            assert stale.status_code == 404
    finally:
        reset_engine()
