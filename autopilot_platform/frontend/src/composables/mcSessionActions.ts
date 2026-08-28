/**
 * 登录 / SSO / 登出。
 */
import type { Ref } from "vue";
import {
  apiErrorMessage,
  beginAuthSession,
  bindSessionChange,
  ensureFreshSession,
  hasRefreshSession,
  loadRefresh,
  noteRefreshCookieActive,
  postIdeHandoffConsume,
  postLogin,
  postLogout,
  saveJwt,
  saveRefresh,
  saveUser,
  tryRefreshSession,
  type AuthUser,
  type TokenPair,
} from "../api";
import * as S from "./mcSessionState";
import {
  runners,
  managedRunner,
  devices,
  dispatchDevices,
  deviceBoard,
  jobs,
  artifacts,
  appBuilds,
} from "./mcExecState";
import { closeJobLog, closeJobReport } from "./mcExecActions";
import { resolvePersonaLandingTab } from "./personaLanding";
import { filterProjectId, orgs } from "./mcProjectsState";
import type { RefreshScope } from "./mcRefreshScopes";

export type SessionDeps = {
  activeTab: Ref<string>;
  refreshOrgs: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  refreshForTab: (tab?: string) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  onAuthChanged?: () => void;
  onAuthCleared?: () => void;
};

let d: SessionDeps;
let sessionChangeBound = false;
let lastPlatformBootId = "";

export async function ensurePlatformBootFresh(
  refreshScopes: (scopes: RefreshScope[]) => Promise<void>,
) {
  try {
    const h = (await fetch("/health").then((r) => r.json())) as Record<string, unknown>;
    const bootId = String(h.platform_boot_id || "");
    if (bootId && lastPlatformBootId && bootId !== lastPlatformBootId) {
      await refreshScopes(["runners", "devices", "managed-runner"]);
    }
    if (bootId) lastPlatformBootId = bootId;
  } catch {
    /* Platform 不可达时保留现有 UI，待恢复后由下次 poll 纠正 */
  }
}

export function bindSessionDeps(deps: SessionDeps): void {
  d = deps;
  if (!sessionChangeBound) {
    sessionChangeBound = true;
    bindSessionChange((session) => {
      if (!session) {
        S.jwt.value = "";
        S.user.value = null;
        d?.onAuthCleared?.();
        return;
      }
      S.jwt.value = session.access_token;
      if (session.user) S.user.value = session.user;
      d?.onAuthChanged?.();
    });
  }
}

function requireDeps(): SessionDeps {
  if (!d) throw new Error("bindSessionDeps() must be called before session actions");
  return d;
}

export async function refreshSsoStatus() {
  try {
    const [o, s] = await Promise.all([
      fetch("/api/v1/auth/oidc/status").then((r) => r.json()),
      fetch("/api/v1/auth/saml/status").then((r) => r.json()),
    ]);
    S.oidcEnabled.value = Boolean(o?.enabled);
    S.samlEnabled.value = Boolean(s?.enabled);
  } catch {
    S.oidcEnabled.value = false;
    S.samlEnabled.value = false;
  }
}

export function onOidcLogin() {
  window.location.href = "/api/v1/auth/oidc/start";
}

export function onSamlLogin() {
  window.location.href = "/api/v1/auth/saml/login";
}

function roleFromJwt(token: string, fallback: string): string {
  try {
    const part = token.split(".")[1];
    if (!part) return fallback;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(pad)) as { role?: string };
    const role = (payload.role || "").trim();
    return role || fallback;
  } catch {
    return fallback;
  }
}

function clearSsoParams(url: URL, hashParams: URLSearchParams, searchParams: URLSearchParams) {
  ["oidc", "saml", "ide", "code", "access_token", "refresh_token", "username", "role", "user_id"].forEach(
    (k) => {
      searchParams.delete(k);
      hashParams.delete(k);
    },
  );
  const nextHash = hashParams.toString();
  url.hash = nextHash ? `#${nextHash}` : "";
  window.history.replaceState({}, "", url.pathname + url.search + url.hash);
}

export async function consumeSsoCallbackFromUrl(): Promise<boolean> {
  const url = new URL(window.location.href);
  const hashRaw = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
  const hashParams = new URLSearchParams(hashRaw);
  const searchParams = url.searchParams;
  const isIde =
    hashParams.get("ide") === "1" || searchParams.get("ide") === "1";
  const via =
    isIde ||
    hashParams.get("oidc") === "1" ||
    hashParams.get("saml") === "1" ||
    searchParams.get("oidc") === "1" ||
    searchParams.get("saml") === "1";
  if (!via) return false;

  const ideCode = (hashParams.get("code") || searchParams.get("code") || "").trim();
  if (isIde && ideCode) {
    clearSsoParams(url, hashParams, searchParams);
    try {
      const out = await postIdeHandoffConsume(ideCode);
      await applyAuthSession(out);
      return true;
    } catch {
      return false;
    }
  }
  if (isIde) {
    // 旧版把 JWT 写进 hash：忽略，避免地址栏令牌继续生效
    clearSsoParams(url, hashParams, searchParams);
    return false;
  }

  const token =
    hashParams.get("access_token") || searchParams.get("access_token") || "";
  const refresh =
    hashParams.get("refresh_token") || searchParams.get("refresh_token") || "";
  const username =
    hashParams.get("username") || searchParams.get("username") || "";
  const user_id =
    hashParams.get("user_id") || searchParams.get("user_id") || "";
  const roleHint =
    hashParams.get("role") || searchParams.get("role") || "operator";
  if (!token || !username) return false;
  const role = roleFromJwt(token, roleHint);
  beginAuthSession();
  S.jwt.value = token;
  S.user.value = { id: user_id, username, role };
  saveJwt(token);
  if (refresh) saveRefresh(refresh);
  saveUser(S.user.value);
  clearSsoParams(url, hashParams, searchParams);
  requireDeps().onAuthChanged?.();
  return true;
}

export async function refreshHealth() {
  try {
    const h = (await fetch("/health").then((r) => r.json())) as Record<string, unknown>;
    S.healthOk.value = h.status === "ok";
    const bootId = String(h.platform_boot_id || "");
    if (bootId) lastPlatformBootId = bootId;
  } catch {
    S.healthOk.value = false;
  }
}

export async function onLogin(ev: Event) {
  ev.preventDefault();
  S.loginError.value = "";
  try {
    const out = await postLogin(S.loginForm.username, S.loginForm.password);
    await applyAuthSession(out);
  } catch (e) {
    S.loginError.value = apiErrorMessage(e);
  }
}

export async function applyAuthSession(
  accessOrPair: string | TokenPair,
  u?: AuthUser,
) {
  const deps = requireDeps();
  beginAuthSession();
  if (typeof accessOrPair === "string") {
    S.jwt.value = accessOrPair;
    if (u) S.user.value = u;
    saveJwt(accessOrPair);
    if (u) saveUser(u);
  } else {
    S.jwt.value = accessOrPair.access_token;
    S.user.value = accessOrPair.user;
    saveJwt(accessOrPair.access_token);
    saveUser(accessOrPair.user);
    if (accessOrPair.refresh_token) {
      // postLogin 已 Set-Cookie + noteRefreshCookieActive；邀请等路径需 body 换 Cookie
      if (hasRefreshSession() && !loadRefresh()) {
        noteRefreshCookieActive();
      } else {
        saveRefresh(accessOrPair.refresh_token);
        await tryRefreshSession();
      }
    }
  }
  deps.onAuthChanged?.();
  await deps.refreshOrgs();
  await deps.refreshProjects();
  // B2：仅当仍停在默认 dashboard 时按人设纠偏，不覆盖深链
  const cur = (deps.activeTab.value || "dashboard").trim() || "dashboard";
  if (cur === "dashboard") {
    const role = String(S.user.value?.role || "").trim();
    const isPlatformAdmin = role === "admin";
    const isOrgAdmin =
      isPlatformAdmin ||
      (orgs.value || []).some(
        (o) => o.my_role === "owner" || o.my_role === "admin",
      );
    const next = resolvePersonaLandingTab({
      isPlatformAdmin,
      isOrgAdmin,
      hasProjectSelected: Boolean(filterProjectId.value.trim()),
    });
    if (next !== cur) deps.activeTab.value = next;
  }
  await deps.refreshForTab(deps.activeTab.value || "dashboard");
  deps.startPolling();
}

export async function onLogout() {
  const deps = requireDeps();
  deps.stopPolling();
  closeJobLog();
  closeJobReport();
  lastPlatformBootId = "";
  await postLogout();
  S.jwt.value = "";
  S.user.value = null;
  runners.value = [];
  managedRunner.value = null;
  devices.value = [];
  dispatchDevices.value = [];
  deviceBoard.value = null;
  jobs.value = [];
  artifacts.value = [];
  appBuilds.value = [];
  deps.onAuthCleared?.();
}

export async function bootstrap() {
  const deps = requireDeps();
  await refreshSsoStatus();
  const fromSso = await consumeSsoCallbackFromUrl();
  void refreshHealth();
  if (!(fromSso || S.loggedIn.value || hasRefreshSession())) {
    S.sessionHydrating.value = false;
    return;
  }
  S.sessionHydrating.value = true;
  try {
    const ready = await ensureFreshSession();
    if (!ready) return;
    await deps.refreshForTab(deps.activeTab.value);
    deps.startPolling();
  } finally {
    S.sessionHydrating.value = false;
  }
}
