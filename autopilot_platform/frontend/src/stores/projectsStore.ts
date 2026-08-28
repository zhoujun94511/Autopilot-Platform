/**
 * 组织 / 项目 Pinia Store：与 useMcStore 共用 mcProjectsState。
 */
import { defineStore } from "pinia";
import * as P from "../composables/mcProjectsState";
import * as ProjectsActions from "../composables/mcProjectsActions";

export const useProjectsStore = defineStore("projects", () => {
  return {
    projectForm: P.projectForm,
    projects: P.projects,
    projectMsg: P.projectMsg,
    memberForm: P.memberForm,
    memberMsg: P.memberMsg,
    filterProjectId: P.filterProjectId,
    filterOrgId: P.filterOrgId,
    orgs: P.orgs,
    refreshOrgs: ProjectsActions.refreshOrgs,
    refreshProjects: ProjectsActions.refreshProjects,
    selectOrg: ProjectsActions.selectOrg,
    selectProject: ProjectsActions.selectProject,
    onCreateProject: ProjectsActions.onCreateProject,
    onAddMember: ProjectsActions.onAddMember,
    onRemoveMember: ProjectsActions.onRemoveMember,
  };
});
