/**
 * 会话 / SSO 状态（单一真源）。
 * useMcStore 与 useAuthStore 共用同一批 ref。
 */
import { computed, reactive, ref } from "vue";
import { loadJwt, loadUser, type AuthUser } from "../api";
import { filterOrgId, orgs } from "./mcProjectsState";

export const jwt = ref(loadJwt());
export const user = ref<AuthUser | null>(loadUser());
export const loggedIn = computed(() => Boolean(jwt.value && user.value));
/** F5 冷启动：有持久化 hint / 用户缓存时先换票，避免闪登录页。 */
export const sessionHydrating = ref(Boolean(loadUser()) && !loadJwt());
export const isPlatformAdmin = computed(() => user.value?.role === "admin");

export const canManageUsers = computed(() => {
  if (isPlatformAdmin.value) return true;
  const oid = filterOrgId.value.trim();
  if (!oid) return false;
  const org = orgs.value.find((o) => o.id === oid);
  return Boolean(org && (org.my_role === "owner" || org.my_role === "admin"));
});

export const loginForm = reactive({ username: "", password: "" });
export const loginError = ref("");
export const oidcEnabled = ref(false);
export const samlEnabled = ref(false);
export const healthOk = ref<boolean | null>(null);
