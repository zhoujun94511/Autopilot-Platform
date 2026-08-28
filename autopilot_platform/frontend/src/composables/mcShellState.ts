/**
 * Shell 导航状态（activeTab / ops 深链 / 页面可见性）。
 * useShellStore 与 platformRuntime 共用同一批 ref。
 */
import type { Router } from "vue-router";
import { ref } from "vue";
import { notify } from "./useNotify";
import { goToOpsCategory } from "../navigation/tabSync";
import { isPlatformAdmin } from "./mcSessionState";

export const activeTab = ref("dashboard");
/** 运维配置中心深链：打开 ops 后 OpsPanel 消费并清空 */
export const opsFocusCategory = ref("");
export const error = ref("");
export const pageVisible = ref(
  typeof document === "undefined" ? true : document.visibilityState !== "hidden",
);

let wiredRouter: Router | null = null;

export function setShellRouter(router: Router | null) {
  wiredRouter = router;
}

export function getShellRouter(): Router | null {
  return wiredRouter;
}

export function openOpsConfig(category = "ai_model") {
  if (!isPlatformAdmin.value) {
    notify("模型与密钥需由平台管理员在「运维」中配置，请联系管理员。", "warn");
    return;
  }
  if (wiredRouter) {
    goToOpsCategory(wiredRouter, activeTab, opsFocusCategory, category);
    return;
  }
  opsFocusCategory.value = category || "ai_model";
  activeTab.value = "ops";
}

export function consumeOpsFocusCategory(): string {
  const v = (opsFocusCategory.value || "").trim();
  opsFocusCategory.value = "";
  return v;
}
