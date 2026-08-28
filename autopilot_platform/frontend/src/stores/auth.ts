/**
 * Auth Pinia Store：与 useMcStore 共用 mcSessionState（真源）。
 */
import { defineStore } from "pinia";
import * as S from "../composables/mcSessionState";
import * as SessionActions from "../composables/mcSessionActions";

export const useAuthStore = defineStore("auth", () => {
  return {
    jwt: S.jwt,
    user: S.user,
    loggedIn: S.loggedIn,
    sessionHydrating: S.sessionHydrating,
    isPlatformAdmin: S.isPlatformAdmin,
    canManageUsers: S.canManageUsers,
    loginForm: S.loginForm,
    loginError: S.loginError,
    oidcEnabled: S.oidcEnabled,
    samlEnabled: S.samlEnabled,
    healthOk: S.healthOk,
    refreshSsoStatus: SessionActions.refreshSsoStatus,
    onOidcLogin: SessionActions.onOidcLogin,
    onSamlLogin: SessionActions.onSamlLogin,
    consumeSsoCallbackFromUrl: SessionActions.consumeSsoCallbackFromUrl,
    refreshHealth: SessionActions.refreshHealth,
    onLogin: SessionActions.onLogin,
    applyAuthSession: SessionActions.applyAuthSession,
    onLogout: SessionActions.onLogout,
    bootstrap: SessionActions.bootstrap,
  };
});
