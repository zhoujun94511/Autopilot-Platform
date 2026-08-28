/**
 * activeTab ↔ vue-router 双向同步（业务仍写 store.activeTab）。
 *
 * 子区约定（query，不另开 path）：
 * - devices: ?section=devices|pools|runners
 * - projects: ?section=org|collab
 * - ops: ?category=<opsFocusCategory>
 */
import type { Router } from "vue-router";
import { watch, type Ref } from "vue";
import { normalizeTabId, pathForTab, tabFromPath } from "../router/tabs";

export type TabSyncHandles = {
  activeTab: Ref<string>;
  opsFocusCategory: Ref<string>;
  onHubSection?: (tab: string, section: string) => void;
};

let installed = false;
let suppressRoutePush = false;

export function applyTabFromRoute(activeTab: Ref<string>, tab: string) {
  suppressRoutePush = true;
  activeTab.value = normalizeTabId(tab);
  suppressRoutePush = false;
}

function querySection(router: Router): string {
  const q = router.currentRoute.value.query.section;
  return typeof q === "string" ? q.trim() : "";
}

function queryCategory(router: Router): string {
  const q = router.currentRoute.value.query.category;
  return typeof q === "string" ? q.trim() : "";
}

export function installTabRouteSync(router: Router, handles: TabSyncHandles): void {
  if (installed) return;
  installed = true;

  const boot = router.currentRoute.value;
  applyTabFromRoute(handles.activeTab, tabFromPath(boot.path));
  const bootCat = queryCategory(router);
  if (bootCat) handles.opsFocusCategory.value = bootCat;
  const bootTab = tabFromPath(boot.path);
  const bootSec = querySection(router);
  if (bootSec && handles.onHubSection) handles.onHubSection(bootTab, bootSec);

  watch(
    handles.activeTab,
    (tab) => {
      if (suppressRoutePush) return;
      const target = pathForTab(tab);
      const cur = router.currentRoute.value;
      if (cur.path === target) return;
      // 保留同 Tab 下已有 query（子区）；跨 Tab 清空
      void router.push({ path: target });
    },
  );

  router.afterEach((to) => {
    const tab = tabFromPath(to.path);
    if (normalizeTabId(handles.activeTab.value) !== tab) {
      applyTabFromRoute(handles.activeTab, tab);
    }
    const cat = typeof to.query.category === "string" ? to.query.category.trim() : "";
    if (cat) handles.opsFocusCategory.value = cat;
    const sec = typeof to.query.section === "string" ? to.query.section.trim() : "";
    if (sec && handles.onHubSection) handles.onHubSection(tab, sec);
  });
}

export function goToOpsCategory(
  router: Router,
  activeTab: Ref<string>,
  opsFocusCategory: Ref<string>,
  category: string,
) {
  const cat = (category || "ai_model").trim() || "ai_model";
  opsFocusCategory.value = cat;
  suppressRoutePush = true;
  activeTab.value = "ops";
  suppressRoutePush = false;
  void router.push({ path: "/admin/ops", query: { category: cat } });
}

export function goToHubSection(router: Router, tab: "devices" | "projects", section: string) {
  const path = pathForTab(tab);
  void router.push({ path, query: section ? { section } : {} });
}
