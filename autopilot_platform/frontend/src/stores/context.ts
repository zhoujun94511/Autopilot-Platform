/**
 * Org / Project 上下文：与 mcProjectsState 共用同一批 ref（真源）。
 */
import { defineStore } from "pinia";
import * as P from "../composables/mcProjectsState";

export const useContextStore = defineStore("context", () => {
  return {
    filterOrgId: P.filterOrgId,
    filterProjectId: P.filterProjectId,
    orgs: P.orgs,
    projects: P.projects,
  };
});
