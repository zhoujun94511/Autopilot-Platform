import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from "vue-router";
import { TAB_ROUTES } from "./tabs";
import { TAB_PANEL_LOADERS, TAB_PANEL_NAMES } from "./panels";

/**
 * Phase3+：路由组件 = 懒加载 Panel；主区 <RouterView>+KeepAlive。
 */
const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/dashboard" },
  {
    path: "/login",
    name: "login",
    component: { template: "<div/>", name: "LoginPlaceholder" },
    meta: { guest: true },
  },
  ...TAB_ROUTES.map((def) => ({
    path: def.path,
    name: def.tab,
    component: TAB_PANEL_LOADERS[def.tab],
    meta: {
      tab: def.tab,
      guards: def.guards,
      label: def.label,
      scopes: def.scopes,
      panelName: TAB_PANEL_NAMES[def.tab],
    },
  })),
  { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
