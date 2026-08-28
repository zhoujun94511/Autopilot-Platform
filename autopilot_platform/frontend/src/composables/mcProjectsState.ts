/**
 * 组织 / 项目上下文状态（单一真源）。
 * useMcStore 与 useContextStore / useProjectsStore 共用。
 */
import { reactive, ref } from "vue";
import { loadOrgId } from "../api";
import type { Organization } from "../api/orgs";

export type ProjectRow = {
  id: string;
  name: string;
  my_role?: string;
  org_id?: string;
  description?: string;
};

const PROJECT_FILTER_KEY = "mc_filter_project_id";

export function loadStoredProjectId(): string {
  try {
    return (localStorage.getItem(PROJECT_FILTER_KEY) || "").trim();
  } catch {
    return "";
  }
}

export function persistProjectId(id: string) {
  try {
    const v = (id || "").trim();
    if (v) localStorage.setItem(PROJECT_FILTER_KEY, v);
    else localStorage.removeItem(PROJECT_FILTER_KEY);
  } catch {
    /* ignore */
  }
}

export const PROJECT_FILTER_STORAGE_KEY = PROJECT_FILTER_KEY;

export const projectForm = reactive({ id: "", name: "" });
export const projects = ref<ProjectRow[]>([]);
export const projectMsg = ref("");
export const memberForm = reactive({ project_id: "", username: "", role: "member" });
export const memberMsg = ref("");

export const filterProjectId = ref(loadStoredProjectId());
export const filterOrgId = ref(loadOrgId());
export const orgs = ref<Organization[]>([]);
