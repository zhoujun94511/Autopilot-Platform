/**
 * Shell Pinia Store：导航 Tab / ops 深链 / 全局 error / 页面可见性。
 */
import { defineStore } from "pinia";
import * as Shell from "../composables/mcShellState";
import * as Polling from "../composables/mcPolling";

export const useShellStore = defineStore("shell", () => {
  return {
    activeTab: Shell.activeTab,
    opsFocusCategory: Shell.opsFocusCategory,
    error: Shell.error,
    pageVisible: Shell.pageVisible,
    openOpsConfig: Shell.openOpsConfig,
    consumeOpsFocusCategory: Shell.consumeOpsFocusCategory,
    refreshScopes: Polling.refreshScopes,
    refreshForTab: Polling.refreshForTab,
    refreshAll: Polling.refreshAll,
    setPageVisible: Polling.setPageVisible,
    startPolling: Polling.startPolling,
    stopPolling: Polling.stopPolling,
  };
});
