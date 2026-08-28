"""前端人设能力档契约白盒（无 Vitest 时用纯 Python 钉死规则 + 源码对齐）。

规则真源：RBAC_BOUNDARY_CONTRACT.md + useCapabilities.ts / roleLabels.ts
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"


def derive_persona_capabilities(
    *,
    logged_in: bool,
    is_platform_admin: bool,
    filter_project_id: str,
    my_role: str,
    can_manage_users: bool,
    filter_org_id: str = "",
    org_my_role: str = "",
    orgs_any_admin: bool = False,
    project_org_id: str = "",
    project_org_my_role: str = "",
    members_can_create_projects: bool = False,
    members_can_invite: bool = False,
) -> dict[str, bool | str]:
    """镜像 frontend useCapabilities / useMcStore 能力派生。"""
    _ = project_org_id
    pid = (filter_project_id or "").strip()
    por = (project_org_my_role or "").strip()
    org_admin_of_project = bool(pid) and (not is_platform_admin) and (
        por in ("owner", "admin")
    )
    if not pid:
        role = ""
    elif is_platform_admin or org_admin_of_project:
        role = "owner"
    else:
        role = (my_role or "").strip()

    oid = (filter_org_id or "").strip()
    if not oid:
        org_role = ""
    else:
        org_role = (org_my_role or "").strip()

    can_ops = bool(is_platform_admin)
    can_manage_org = bool(can_manage_users)
    can_create_org = bool(is_platform_admin)
    can_manage_any_org = bool(
        is_platform_admin or orgs_any_admin
    )
    can_manage_current_org = bool(
        is_platform_admin or org_role in ("owner", "admin")
    )
    can_create_project = bool(oid) and (
        is_platform_admin
        or org_role in ("owner", "admin")
        or (org_role == "member" and members_can_create_projects)
    )
    can_invite_org_member = bool(oid) and (
        can_manage_current_org
        or (org_role == "member" and members_can_invite)
    )
    can_view_cluster = bool(logged_in)
    can_manage_infra = bool(is_platform_admin or can_manage_users)
    can_manage_runners = bool(is_platform_admin)
    can_view_ops_budget = bool(is_platform_admin)
    can_share_read = bool(logged_in)
    can_share_write = bool(
        is_platform_admin
        or (logged_in and not pid)
        or (bool(pid) and (is_platform_admin or role in ("owner", "member")))
    )
    can_view = bool(pid) and (
        is_platform_admin or role in ("owner", "member", "viewer")
    )
    can_edit = bool(pid) and (is_platform_admin or role in ("owner", "member"))
    can_manage_project = bool(pid) and (is_platform_admin or role == "owner")
    is_viewer = bool(pid) and (not is_platform_admin) and role == "viewer"
    return {
        "currentProjectRole": role,
        "currentOrgRole": org_role,
        "canOps": can_ops,
        "canManageOrg": can_manage_org,
        "canCreateOrg": can_create_org,
        "canManageAnyOrg": can_manage_any_org,
        "canManageCurrentOrg": can_manage_current_org,
        "canCreateProject": can_create_project,
        "canInviteOrgMember": can_invite_org_member,
        "canViewCluster": can_view_cluster,
        "canManageInfra": can_manage_infra,
        "canManageRunners": can_manage_runners,
        "canViewOpsBudget": can_view_ops_budget,
        "canShareRead": can_share_read,
        "canShareWrite": can_share_write,
        "canViewProject": can_view,
        "canEditProject": can_edit,
        "canManageProject": can_manage_project,
        "isProjectViewer": is_viewer,
    }


@pytest.mark.parametrize(
    ("admin", "pid", "role", "org_admin", "expect"),
    [
        # 未选项目：不可视/不可写
        (False, "", "", False, {
            "canViewProject": False,
            "canEditProject": False,
            "canManageProject": False,
            "canOps": False,
            "isProjectViewer": False,
        }),
        # 普通 member
        (False, "p1", "member", False, {
            "canViewProject": True,
            "canEditProject": True,
            "canManageProject": False,
            "canOps": False,
            "isProjectViewer": False,
            "currentProjectRole": "member",
        }),
        # viewer 只读
        (False, "p1", "viewer", False, {
            "canViewProject": True,
            "canEditProject": False,
            "canManageProject": False,
            "isProjectViewer": True,
            "currentProjectRole": "viewer",
        }),
        # project owner
        (False, "p1", "owner", False, {
            "canEditProject": True,
            "canManageProject": True,
            "isProjectViewer": False,
        }),
        # 平台 admin：视同 owner + ops
        (True, "p1", "viewer", False, {
            "currentProjectRole": "owner",
            "canEditProject": True,
            "canManageProject": True,
            "canOps": True,
            "isProjectViewer": False,
        }),
        # 组织管理员但未知项目所属组织：不能凭顶栏身份改写项目角色
        (False, "p1", "viewer", True, {
            "canManageOrg": True,
            "canEditProject": False,
            "canManageProject": False,
            "canOps": False,
            "isProjectViewer": True,
            "currentProjectRole": "viewer",
        }),
    ],
)
def test_capability_matrix(admin, pid, role, org_admin, expect):
    got = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=admin,
        filter_project_id=pid,
        my_role=role,
        can_manage_users=org_admin or admin,
    )
    for k, v in expect.items():
        assert got[k] == v, f"{k}: got={got[k]!r} expect={v!r} full={got}"


def test_role_labels_source_contract():
    text = (FE / "components" / "projects" / "roleLabels.ts").read_text(encoding="utf-8")
    assert 'operator: "普通用户"' in text
    assert 'admin: "系统管理员"' in text
    assert 'admin: "组织管理员"' in text
    assert 'owner: "项目负责人"' in text
    assert 'owner: "组织负责人"' in text
    assert 'viewer: "只读"' in text
    assert "export function platformRoleLabel" in text
    assert "export function orgRoleLabel" in text
    assert "export function projectRoleLabel" in text


def test_users_panel_create_duty_one_step():
    """注册时一次选「来干什么」，系统管理员与项目负责人分开，不再只丢 operator/admin。"""
    src = (FE / "components" / "UsersPanel.vue").read_text(encoding="utf-8")
    assert "dutyOptions" in src
    assert "这个人来干什么" in src
    assert "sys_admin" in src
    assert "org_admin" in src
    assert "project_owner" in src
    assert "系统管理员" in src
    assert "项目负责人" in src or "管「" in src
    assert "label: 'operator'" not in src
    assert "onCreateUser" in src
    assert "orgId" in src
    assert "projectId" in src
    actions = (FE / "composables" / "mcAdminActions.ts").read_text(encoding="utf-8")
    assert 'duty,' in actions or "duty," in actions
    assert "body.project_id" in actions
    assert "org_role" not in actions
    assert "project_role" not in actions
    create_chunk = actions.split("const body")[1].split("try {")[0]
    assert "role:" not in create_chunk


def test_use_capabilities_source_gates():
    text = (FE / "composables" / "useCapabilities.ts").read_text(encoding="utf-8")
    assert "canEditProject" in text
    assert "canManageProject" in text
    assert "canOps" in text
    assert "canShareRead" in text
    assert "canShareWrite" in text
    assert "canManageRunners" in text
    assert "canViewCluster" in text
    assert "canCreateOrg" in text
    assert "canManageAnyOrg" in text
    assert "canManageCurrentOrg" in text
    assert "canCreateProject" in text
    assert "canInviteOrgMember" in text
    assert "members_can_create_projects" in text
    assert 'r === "viewer"' in text or "=== \"viewer\"" in text
    # 无项目不可编辑
    assert "if (!pid) return false" in text
    # 本组织 owner/admin 对本组织项目 ≡ 项目 owner
    assert "isOrgAdminOfCurrentProject" in text


def test_open_ops_config_non_admin_guard_in_store():
    text = (FE / "composables" / "mcShellState.ts").read_text(encoding="utf-8")
    assert "function openOpsConfig" in text
    assert "isPlatformAdmin" in text
    assert "联系" in text and "管理员" in text
    # 非 admin 不得切到 ops
    fn = re.search(
        r"function openOpsConfig\([\s\S]*?\n}",
        text,
    )
    assert fn, "openOpsConfig 未找到"
    body = fn.group(0)
    assert "activeTab.value = \"ops\"" in body or "activeTab.value = 'ops'" in body
    assert "if (!isPlatformAdmin" in body or "if (!isPlatformAdmin.value)" in body


def test_app_vue_persona_guards():
    text = (FE / "App.vue").read_text(encoding="utf-8")
    assert "platformRoleLabel" in text
    assert "guardAdminTabs" in text
    assert "design-config" in text
    # 顶栏健康仅 admin（canOps）
    assert "caps.canOps" in text
    # 共享 / 设备侧栏：已登录即可见（写操作在 SharePanel / RunnersPanel 内门禁）
    assert "showShareNav" in text
    assert "showDevicesNav" in text
    assert "v-if=\"showShareNav\"" in text
    assert "v-if=\"showDevicesNav\"" in text
    assert "loggedIn" in text
    assert "useAuthStore" in text


def test_nav_visibility_matrix_for_operator():
    """已登录用户可见共享/设备；运维侧栏仍仅 platform admin。"""
    caps = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="member",
        can_manage_users=False,
    )
    assert caps["canShareRead"] is True
    assert caps["canShareWrite"] is True
    assert caps["canViewCluster"] is True
    assert caps["canOps"] is False
    assert caps["canManageRunners"] is False

    viewer = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="viewer",
        can_manage_users=False,
    )
    assert viewer["canShareRead"] is True
    assert viewer["canShareWrite"] is False
    assert viewer["isProjectViewer"] is True


def test_projects_panel_no_create_org_cta_for_members():
    """普通成员不得被文案诱导去「创建/配置组织」。"""
    panel = (FE / "components" / "ProjectsPanel.vue").read_text(encoding="utf-8")
    assert "useCapabilities" in panel
    assert "caps.canCreateOrg || caps.canManageAnyOrg" in panel
    assert "caps.canCreateProject" in panel
    assert "组织由管理员创建" in panel or "无法自行创建" in panel

    org = (FE / "components" / "projects" / "OrgSettingsSection.vue").read_text(
        encoding="utf-8"
    )
    assert "useCapabilities" in org
    assert 'v-if="caps.canCreateOrg"' in org
    assert "caps.canManageCurrentOrg" in org
    assert "caps.canInviteOrgMember" in org
    assert "patchOrgPolicies" in org
    assert "members_can_create_projects" in org
    assert "无法自行创建" in org
    # 未选组织时不得展示禁用的加人表单
    assert "也可先在左侧创建组织" not in org

    plist = (FE / "components" / "projects" / "ProjectList.vue").read_text(
        encoding="utf-8"
    )
    assert "useCapabilities" in plist
    assert "caps.canManageAnyOrg" in plist
    assert "caps.canCreateProject" in plist
    assert "组织无法自行创建" in plist


def test_use_capabilities_returns_reactive_object():
    """能力档必须以 reactive 返回，避免模版里 caps.xxx 恒为真。"""
    text = (FE / "composables" / "useCapabilities.ts").read_text(encoding="utf-8")
    assert "return reactive(" in text
    assert "from \"vue\"" in text or "from 'vue'" in text


def test_capability_refs_not_double_unwrapped_in_templates():
    """reactive 解包后，模版/脚本不应再写 caps.xxx.value（会变成访问布尔值的 .value）。"""
    bad = re.compile(r"caps\.[A-Za-z]\w*\.value\b")
    offenders: list[str] = []
    for path in sorted(FE.rglob("*.vue")) + sorted(FE.rglob("*.ts")):
        if path.name == "useCapabilities.ts":
            continue
        text = path.read_text(encoding="utf-8")
        for hit in bad.finditer(text):
            offenders.append(f"{path.relative_to(FE)}: {hit.group(0)}")
    assert not offenders, "reactive 能力档不应再写 .value：" + "; ".join(offenders)


def test_org_capability_derivation():
    admin = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=True,
        filter_project_id="",
        my_role="",
        can_manage_users=True,
    )
    assert admin["canCreateOrg"] is True
    assert admin["canManageAnyOrg"] is True

    org_admin = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="member",
        can_manage_users=True,
        filter_org_id="o1",
        org_my_role="admin",
        orgs_any_admin=True,
    )
    assert org_admin["canCreateOrg"] is False
    assert org_admin["canManageAnyOrg"] is True
    assert org_admin["canManageCurrentOrg"] is True
    assert org_admin["canCreateProject"] is True
    assert org_admin["canInviteOrgMember"] is True
    assert org_admin["currentOrgRole"] == "admin"

    member = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="member",
        can_manage_users=False,
        orgs_any_admin=False,
    )
    assert member["canManageAnyOrg"] is False
    assert member["canCreateOrg"] is False
    assert member["canCreateProject"] is False
    assert member["canInviteOrgMember"] is False

    member_in_org = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="member",
        can_manage_users=False,
        filter_org_id="o1",
        org_my_role="member",
        orgs_any_admin=False,
    )
    assert member_in_org["canManageCurrentOrg"] is False
    assert member_in_org["canCreateProject"] is False
    assert member_in_org["canInviteOrgMember"] is False

    member_allowed = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="member",
        can_manage_users=False,
        filter_org_id="o1",
        org_my_role="member",
        orgs_any_admin=False,
        members_can_create_projects=True,
        members_can_invite=True,
    )
    assert member_allowed["canManageCurrentOrg"] is False
    assert member_allowed["canCreateProject"] is True
    assert member_allowed["canInviteOrgMember"] is True


def test_org_admin_of_project_org_without_current_org_filter():
    """本组织管理员：即使顶栏是「全部组织」，对本组织项目仍是管理者。"""
    caps = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="p1",
        my_role="viewer",
        can_manage_users=False,
        filter_org_id="",
        project_org_id="o1",
        project_org_my_role="admin",
        orgs_any_admin=True,
    )
    assert caps["canEditProject"] is True
    assert caps["canManageProject"] is True
    assert caps["isProjectViewer"] is False
    assert caps["currentProjectRole"] == "owner"


def test_dashboard_layout_is_capability_gated_not_forked():
    """首页只有一份模板：角色只藏运维卡，不得再分叉「快捷入口」四宫格。"""
    src = (FE / "components" / "DashboardPanel.vue").read_text(encoding="utf-8")
    assert "dash-quick-row" in src
    assert "全部任务" in src
    assert "快捷入口" not in src
    assert "btn-quick" not in src
    assert "caps.canManageInfra" in src
    assert "caps.canOps" in src
    dist_dir = ROOT / "autopilot_platform" / "frontend" / "dist" / "assets"
    for js in dist_dir.glob("DashboardPanel-*.js"):
        built = js.read_text(encoding="utf-8")
        assert "dash-quick-row" in built, f"stale dist {js.name}: rebuild frontend"
        assert "快捷入口" not in built, f"stale dist {js.name}: still has old operator layout"


def test_design_panels_wire_can_edit():
    """关键设计面板必须门禁 canEditProject / ProjectReadonlyBanner。"""
    cases = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "canEditProject" in cases or "canEdit" in cases
    assert "ProjectReadonlyBanner" in cases

    docs = (FE / "components" / "design" / "DesignDocsPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "ProjectReadonlyBanner" in docs
    assert "canEdit" in docs

    knowledge = (FE / "components" / "design" / "DesignKnowledgePanel.vue").read_text(
        encoding="utf-8"
    )
    assert "ProjectReadonlyBanner" in knowledge
    assert "canEdit" in knowledge

    chat = (FE / "components" / "design" / "DesignChatPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "ProjectReadonlyBanner" in chat
    assert "useCapabilities" in chat
    assert "caps.canOps" in chat
    assert "联系" in chat and ("管理员" in chat or "平台管理员" in chat)

    workspace = (FE / "components" / "projects" / "ProjectWorkspace.vue").read_text(
        encoding="utf-8"
    )
    assert "useCapabilities" in workspace
    assert "caps.canManageProject" in workspace


def test_use_mc_store_no_duplicate_capability_exports():
    """项目/运维能力档仅由 useCapabilities 导出，runtime 接线文件不再重复。"""
    text = (FE / "composables" / "platformRuntime.ts").read_text(encoding="utf-8")
    assert "export function useMcStore(" not in text
    for key in (
        "canEditProject",
        "canManageProject",
        "isProjectViewer",
        "canViewProject",
        "canOps",
        "canManageOrg",
        "currentProjectRole",
    ):
        assert key not in text, f"useMcStore/runtime 仍导出或提及 {key}，请改用 useCapabilities"


def test_design_panels_use_capabilities_not_store_project_gates():
    """设计/任务面板应走 useCapabilities，而非 store.canEditProject。"""
    for rel in (
        "components/design/DesignCasesPanel.vue",
        "components/design/DesignDocsPanel.vue",
        "components/design/DesignKnowledgePanel.vue",
        "components/design/DesignCaseGenerateCard.vue",
        "components/design/ProjectReadonlyBanner.vue",
        "components/JobCreatePanel.vue",
    ):
        text = (FE / rel).read_text(encoding="utf-8")
        assert "useCapabilities" in text, rel
        assert "store.canEditProject" not in text, rel
        assert "store.isProjectViewer" not in text, rel


def test_exec_panels_require_project_gate():
    """A1：执行域创建/上传必须强制项目，禁止「不关联」。"""
    job = (FE / "components" / "JobCreatePanel.vue").read_text(encoding="utf-8")
    assert "不关联" not in job
    assert "请选择项目" in job
    assert "required" in job

    schedules = (FE / "components" / "SchedulesPanel.vue").read_text(encoding="utf-8")
    assert "不关联" not in schedules
    assert "canCreateSchedule" in schedules or "canEditProject" in schedules
    assert "ExecProjectGateBanner" in schedules

    for rel in (
        "components/ArtifactsPanel.vue",
        "components/AppBuildsPanel.vue",
        "components/JobsPanel.vue",
    ):
        text = (FE / rel).read_text(encoding="utf-8")
        assert "ExecProjectGateBanner" in text, rel
        assert "canEditProject" in text or "canUpload" in text or "canCreateJob" in text, rel

    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "批跑必须归属项目" in actions
    assert "制品必须归属项目" in actions
    assert "应用包必须归属项目" in actions
    assert "计划必须归属项目" in actions


def test_design_banners_distinguish_missing_vs_viewer():
    """A2：未选项目 vs 只读成员文案可区分。"""
    ctx = (FE / "components" / "design" / "ProjectContextBanner.vue").read_text(
        encoding="utf-8"
    )
    assert "还没选项目" in ctx or "需要先选择项目" in ctx
    ro = (FE / "components" / "design" / "ProjectReadonlyBanner.vue").read_text(
        encoding="utf-8"
    )
    assert "只读成员" in ro
    assert "viewer" in ro.lower() or "无法生成" in ro


def test_org_switch_clears_cross_org_project():
    """B1：切换组织时清理非法项目并提示。"""
    text = (FE / "composables" / "mcProjectsActions.ts").read_text(encoding="utf-8")
    assert "clearedProject" in text
    assert "已切换组织" in text
    assert "scheduleForm.project_id" in text


def test_persona_landing_helper():
    """B2：人设默认落地 helper 存在且规则与契约一致。"""
    text = (FE / "composables" / "personaLanding.ts").read_text(encoding="utf-8")
    assert "resolvePersonaLandingTab" in text
    assert "design-dashboard" in text
    assert "projects" in text
    session = (FE / "composables" / "mcSessionActions.ts").read_text(encoding="utf-8")
    assert "resolvePersonaLandingTab" in session


def test_device_infra_vs_exec_copy():
    """设备区说明给使用者看：不出现组件名和内部术语。"""
    hub = (FE / "components" / "DevicesHub.vue").read_text(encoding="utf-8")
    assert "DevicePicker" not in hub
    assert "租户" not in hub
    assert "管池" not in hub
    assert "基础设施" not in hub
    assert "自动分配" in hub
    assert "批跑" in hub
    assert 'desc: canOps ? ""' in hub or "canOps ? \"\"" in hub
    picker = (FE / "components" / "DevicePicker.vue").read_text(encoding="utf-8")
    template = picker.split("<template>", 1)[1]
    assert "Device Farm" not in template
    assert "CRUD" not in template
    assert "基础设施" not in template
    assert "管池" not in template
    assert "自动分配" in template
    assert "指定设备" in template


def test_resource_pool_list_is_org_scoped_and_project_is_only_an_assignment():
    """资源池属于组织；顶栏项目不得把组织池列表过滤掉。"""
    panel = (FE / "components" / "ResourcePoolsPanel.vue").read_text(encoding="utf-8")
    assert "filterOrgId" in panel
    assert "filterProjectId" not in panel
    assert 'listResourcePoolsPage(orgId.value, "",' in panel
    assert "setResourcePoolProject" in panel
    assert "当前组织下还没有对你可见的设备池" in panel
    assert "当前项目还没有可用的设备池" not in panel
    assert "设备本身不绑某个项目" in panel


def test_share_read_does_not_require_selected_project():
    """ACL 查看按 resource_id；只有建立/撤销依赖资源所属项目写权限。"""
    panel = (FE / "components" / "SharePanel.vue").read_text(encoding="utf-8")
    assert "filterProjectId" not in panel
    assert "输入或点选资源后可以查看已有分享" in panel
    assert "所属项目的写权限" in panel
    assert 'v-if="caps.canShareWrite"' in panel
    capabilities = (FE / "composables" / "useCapabilities.ts").read_text(
        encoding="utf-8"
    )
    assert "if (!pid) return Boolean(loggedIn.value)" in capabilities


def test_share_write_entry_visible_without_header_project():
    """资源归属只能在选择 resource_id 后判断；API 负责最终写权限。"""
    caps = derive_persona_capabilities(
        logged_in=True,
        is_platform_admin=False,
        filter_project_id="",
        my_role="",
        can_manage_users=False,
    )
    assert caps["canShareRead"] is True
    assert caps["canShareWrite"] is True


def test_page_ledes_avoid_internal_jargon():
    """页头说明、提示、按钮 title 给使用者看，不出现组件名 / 内部架构词。"""
    banned = (
        "DevicePicker",
        "Device Farm",
        "租户边界",
        "基础设施",
        "管池",
        "软隔离",
        "ACL",
        "CRUD",
        "工作主路径",
        "人审",
        "TR 池",
        "Webhook URL",
        "批跑编排",
        "选用授权",
        "Verifier",
        "solidify",
        "Claimed",
        "僵死",
        "已预占",
        "PENDING_VERIFY",
        "intent_steps",
        "Binding",
        "SSE",
    )
    quoted = re.compile(r"""["']([^"'\n]{2,180})["']""")
    hits: list[str] = []
    roots = [FE / "components", FE / "api" / "opsConfig.ts", FE / "composables" / "mcExecActions.ts"]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(sorted(root.rglob("*.vue")))
            files.extend(sorted(root.rglob("*.ts")))
    for path in files:
        text = path.read_text(encoding="utf-8")
        for m in quoted.finditer(text):
            s = m.group(1)
            if len(s) > 180 or not re.search(r"[\u4e00-\u9fff]", s):
                continue
            for token in banned:
                if token in s:
                    hits.append(f"{path.relative_to(FE).as_posix()}: {token} ← {s[:80]}")
    assert hits == [], "用户可见文案不应出现内部术语：\n" + "\n".join(hits)


def test_product_surface_plan_exists():
    plan = ROOT / "docs" / "architecture" / "PRODUCT_SURFACE_AND_REFERENCE_PLAN.md"
    assert plan.is_file()
    text = plan.read_text(encoding="utf-8")
    assert "C-OWN" in text
    assert "Device 不是此类执行资源" in text
    assert "Phase A" in text
