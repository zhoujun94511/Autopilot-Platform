/**
 * 前端能力档 — 对齐 RBAC_BOUNDARY_CONTRACT.md + rbac-capability-matrix.md。
 *
 * 返回 ``reactive`` 包装对象，使模版/脚本中 ``caps.canOps`` 自动解包为布尔值，
 * 避免「普通对象内嵌 ComputedRef → 模版恒真」类门禁失效。
 */
import { storeToRefs } from "pinia";
import { computed, reactive } from "vue";
import { useAuthStore } from "../stores/auth";
import { useProjectsStore } from "../stores/projectsStore";
import { orgPoliciesOf } from "../api/orgs";

export function useCapabilities() {
  const auth = useAuthStore();
  const projects = useProjectsStore();
  const { isPlatformAdmin, canManageUsers, loggedIn } = storeToRefs(auth);
  const { filterProjectId, filterOrgId, projects: projectList, orgs } = storeToRefs(projects);

  /** 本组织 owner/admin：对本组织项目 ≡ 项目 owner（不是覆盖 viewer） */
  const isOrgAdminOfCurrentProject = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid || isPlatformAdmin.value) return false;
    const hit = (projectList.value || []).find((p) => p.id === pid);
    const poid = String((hit as { org_id?: string } | undefined)?.org_id || "").trim();
    if (!poid) return false;
    const org = (orgs.value || []).find((o) => o.id === poid);
    const r = String((org as { my_role?: string } | undefined)?.my_role || "").trim();
    return r === "owner" || r === "admin";
  });

  const currentProjectRole = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid) return "";
    if (isPlatformAdmin.value || isOrgAdminOfCurrentProject.value) return "owner";
    const hit = (projectList.value || []).find((p) => p.id === pid);
    return String((hit as { my_role?: string } | undefined)?.my_role || "").trim();
  });

  /** 平台运维：配置中心、全局预算、purge/reclaim/发 Token */
  const canOps = computed(() => Boolean(isPlatformAdmin.value));

  /** 组织管理：成员/审计（本 org）；不含全局 ops */
  const canManageOrg = computed(() => Boolean(canManageUsers.value));

  /** 集群资源只读：设备 + Runner 列表（全体已登录用户） */
  const canViewCluster = computed(() => Boolean(loggedIn.value));

  /** 运维向指标：离线 Runner 数、设备占用卡、托管 Runner */
  const canManageInfra = computed(
    () => Boolean(isPlatformAdmin.value || canManageUsers.value),
  );

  /** Runner 写操作：发 Token、注销、reclaim、托管 */
  const canManageRunners = computed(() => Boolean(isPlatformAdmin.value));

  /** 全局 AI Token 预算与用量 */
  const canViewOpsBudget = computed(() => Boolean(isPlatformAdmin.value));

  /** 共享 ACL 查看（全体已登录） */
  const canShareRead = computed(() => Boolean(loggedIn.value));

  /**
   * 共享 ACL 建立/撤销入口。
   * 未选顶栏项目时无法在前端推断目标资源归属，先展示入口，最终由 API
   * 按 resource_id 对应项目的写权限判定；已选项目时仍提前拦 viewer。
   */
  const canShareWrite = computed(() => {
    if (isPlatformAdmin.value) return true;
    const pid = String(filterProjectId.value || "").trim();
    if (!pid) return Boolean(loggedIn.value);
    return canEditProject.value;
  });

  const canViewProject = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid) return false;
    if (isPlatformAdmin.value) return true;
    const r = currentProjectRole.value;
    return r === "owner" || r === "member" || r === "viewer";
  });

  const canEditProject = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid) return false;
    if (isPlatformAdmin.value) return true;
    const r = currentProjectRole.value;
    return r === "owner" || r === "member";
  });

  const canManageProject = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid) return false;
    if (isPlatformAdmin.value) return true;
    return currentProjectRole.value === "owner";
  });

  const isProjectViewer = computed(() => {
    const pid = String(filterProjectId.value || "").trim();
    if (!pid || isPlatformAdmin.value) return false;
    return currentProjectRole.value === "viewer";
  });

  const currentOrgRole = computed(() => {
    const oid = String(filterOrgId.value || "").trim();
    if (!oid) return "";
    const hit = (orgs.value || []).find((o) => o.id === oid);
    return String((hit as { my_role?: string } | undefined)?.my_role || "").trim();
  });

  /** 平台管理员可创建组织 */
  const canCreateOrg = computed(() => Boolean(isPlatformAdmin.value));

  /** 至少可管理一个组织（owner/admin），或平台管理员 */
  const canManageAnyOrg = computed(() => {
    if (isPlatformAdmin.value) return true;
    return (orgs.value || []).some(
      (o) => o.my_role === "owner" || o.my_role === "admin",
    );
  });

  /** 当前顶栏选中组织的管理权（加人、改策略）；无选中 org 时仅平台 admin 为 true */
  const canManageCurrentOrg = computed(() => {
    if (isPlatformAdmin.value) return true;
    const r = currentOrgRole.value;
    return r === "owner" || r === "admin";
  });

  const currentOrgPolicies = computed(() => {
    const oid = String(filterOrgId.value || "").trim();
    if (!oid) return orgPoliciesOf(null);
    const hit = (orgs.value || []).find((o) => o.id === oid);
    return orgPoliciesOf(hit);
  });

  /** 在当前组织下新建项目：平台 admin / org owner·admin / 策略放开的 member */
  const canCreateProject = computed(() => {
    const oid = String(filterOrgId.value || "").trim();
    if (!oid) return false;
    if (isPlatformAdmin.value) return true;
    const r = currentOrgRole.value;
    if (r === "owner" || r === "admin") return true;
    return r === "member" && currentOrgPolicies.value.members_can_create_projects;
  });

  /** 邀请同事进当前组织：管理员，或策略放开且仅能邀 member 的普通成员 */
  const canInviteOrgMember = computed(() => {
    const oid = String(filterOrgId.value || "").trim();
    if (!oid) return false;
    if (canManageCurrentOrg.value) return true;
    return currentOrgRole.value === "member" && currentOrgPolicies.value.members_can_invite;
  });

  return reactive({
    currentProjectRole,
    currentOrgRole,
    canOps,
    canManageOrg,
    canCreateOrg,
    canManageAnyOrg,
    canManageCurrentOrg,
    canCreateProject,
    canInviteOrgMember,
    canViewCluster,
    canManageInfra,
    canManageRunners,
    canViewOpsBudget,
    canShareRead,
    canShareWrite,
    canViewProject,
    canEditProject,
    canManageProject,
    isProjectViewer,
  });
}
