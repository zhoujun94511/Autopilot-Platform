/**
 * 路由级能力门禁（与 App.vue guardAdminTabs / tabs.guards 对齐）。
 * 未登录不拦路径，保留深链；登录后由 App 显示 Shell。
 */
import { START_LOCATION, type RouteLocationNormalizedLoaded, type Router } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { pathForTab } from "./tabs";
import type { TabGuard } from "./tabs";

function routeAccessRedirect(to: Pick<RouteLocationNormalizedLoaded, "meta">) {
  const auth = useAuthStore();
  const guards = (to.meta.guards as TabGuard[] | undefined) ?? [];
  if (!auth.loggedIn) return;
  if (guards.includes("ops") && !auth.isPlatformAdmin) return pathForTab("dashboard");
  if (guards.includes("manageUsers") && !auth.canManageUsers) {
    return pathForTab("dashboard");
  }
}

export function installRouteGuards(router: Router): void {
  router.beforeEach((to, from) => {
    // 首次导航先保留深链，会话引导恢复组织角色后再次检查，再读取页面数据。
    if (from === START_LOCATION) return true;
    const path = routeAccessRedirect(to);
    return path ? { path, replace: true } : true;
  });
}

export async function enforceRouteAccess(router: Router): Promise<void> {
  const path = routeAccessRedirect(router.currentRoute.value);
  if (path) await router.replace(path);
}
