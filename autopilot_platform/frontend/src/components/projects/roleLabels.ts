/** 角色中文：按「系统 / 组织 / 项目」分开，避免都叫「管理员」。 */

export const PLATFORM_ROLE_LABEL: Record<string, string> = {
  admin: "系统管理员",
  operator: "普通用户",
};

export const ORG_ROLE_LABEL: Record<string, string> = {
  owner: "组织负责人",
  admin: "组织管理员",
  member: "组织成员",
};

export const PROJECT_ROLE_LABEL: Record<string, string> = {
  owner: "项目负责人",
  member: "项目成员",
  viewer: "只读",
};

/** 无作用域时的兜底（邀请表等混用时尽量别靠这个） */
export const ROLE_LABEL: Record<string, string> = {
  ...ORG_ROLE_LABEL,
  ...PROJECT_ROLE_LABEL,
  admin: ORG_ROLE_LABEL.admin,
};

export function platformRoleLabel(role: string | undefined | null): string {
  const r = (role || "").trim();
  if (!r) return "—";
  return PLATFORM_ROLE_LABEL[r] || r;
}

export function orgRoleLabel(role: string | undefined | null): string {
  const r = (role || "").trim();
  if (!r) return "—";
  return ORG_ROLE_LABEL[r] || r;
}

export function projectRoleLabel(role: string | undefined | null): string {
  const r = (role || "").trim();
  if (!r) return "—";
  return PROJECT_ROLE_LABEL[r] || r;
}

export function roleLabel(role: string | undefined | null): string {
  const r = (role || "").trim();
  if (!r) return "—";
  return ROLE_LABEL[r] || r;
}
