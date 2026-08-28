/**
 * 路由级能力门禁（与 App.vue guardAdminTabs / tabs.guards 对齐）。
 * 未登录不拦路径，保留深链；登录后由 App 显示 Shell。
 */
import type { Router } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { pathForTab } from "./tabs";
import type { TabGuard } from "./tabs";

export function installRouteGuards(router: Router): void {
  router.beforeEach((to) => {
    if (to.meta?.guest) return true;

    const auth = useAuthStore();
    const guards = (to.meta?.guards as TabGuard[] | undefined) || [];

    // 未登录：允许停留在目标 URL，登录后直接进入深链页
    if (!auth.loggedIn) return true;

    if (guards.includes("ops") && !auth.isPlatformAdmin) {
      return { path: pathForTab("dashboard"), replace: true };
    }
    if (guards.includes("manageUsers") && !auth.canManageUsers) {
      return { path: pathForTab("dashboard"), replace: true };
    }
    return true;
  });
}
