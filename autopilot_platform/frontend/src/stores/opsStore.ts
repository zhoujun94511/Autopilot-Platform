/**
 * 运维 / 共享 Pinia Store：与 useMcStore 共用 mcOpsState + mcOpsActions。
 */
import { defineStore } from "pinia";
import * as O from "../composables/mcOpsState";
import * as OpsActions from "../composables/mcOpsActions";

export const useOpsStore = defineStore("ops", () => {
  return {
    ops: O.ops,
    opsConfig: O.opsConfig,
    opsConfigSources: O.opsConfigSources,
    opsConfigMsg: O.opsConfigMsg,
    designAiSummary: O.designAiSummary,
    shareForm: O.shareForm,
    shareMsg: O.shareMsg,
    aclRows: O.aclRows,
    refreshOps: OpsActions.refreshOps,
    onAlertTest: OpsActions.onAlertTest,
    refreshOpsConfig: OpsActions.refreshOpsConfig,
    onSaveOpsConfig: OpsActions.onSaveOpsConfig,
    refreshAcl: OpsActions.refreshAcl,
    onShare: OpsActions.onShare,
    onRevokeAcl: OpsActions.onRevokeAcl,
    selectArtifactForShare: OpsActions.selectArtifactForShare,
    selectAppBuildForShare: OpsActions.selectAppBuildForShare,
    selectJobForShare: OpsActions.selectJobForShare,
    selectScheduleForShare: OpsActions.selectScheduleForShare,
  };
});
