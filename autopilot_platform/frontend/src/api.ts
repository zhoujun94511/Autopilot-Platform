import { apiPath } from "./api/bootstrap";

const JWT_KEY = "mc_jwt";
const REFRESH_KEY = "mc_refresh";
const ORG_KEY = "mc_filter_org_id";
const USER_KEY = "mc_user";
const RUNNER_TOKEN_KEY = "mc_api_token";
/** 非密钥：标记本机曾建立 Cookie 会话，供 F5 冷启动探测 HttpOnly refresh。 */
const SESSION_HINT_KEY = "mc_session";

/** Access JWT 仅存进程内存，不落 localStorage（AUD-2026-02 Phase B）。 */
let accessTokenMem = "";

/**
 * Refresh：优先 HttpOnly Cookie（AUD-2026-02 Phase C）。
 * ``refreshTokenMem`` 仅作 SSO fragment / 邀请接口的短暂交接，不落盘。
 */
let refreshTokenMem = "";
let refreshCookieActive = false;

/** 将 /api/v1/... 或 /auth/... 解析为当前 bootstrap 前缀下的路径。 */
function resolveApiPath(path: string): string {
  const p = (path || "").trim();
  if (!p || p.startsWith("http://") || p.startsWith("https://")) return p;
  return apiPath(p);
}

export type AuthUser = { id: string; username: string; role: string };

export type TokenPair = {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  token_type?: string;
  user: AuthUser;
};

/** 与后端统一错误信封对齐：code / message / error_type / trace_id / details */
export class ApiHttpError extends Error {
  readonly status: number;
  readonly code: string;
  readonly errorType: string;
  readonly detail: string;
  readonly traceId: string;
  readonly details: unknown;

  constructor(
    status: number,
    message: string,
    opts: {
      code?: string;
      errorType?: string;
      traceId?: string;
      details?: unknown;
    } = {},
  ) {
    const msg = (message || "").trim() || `请求失败（${status}）`;
    super(msg);
    this.name = "ApiHttpError";
    this.status = status;
    this.detail = msg;
    this.code = opts.code || "";
    this.errorType = opts.errorType || "";
    this.traceId = opts.traceId || "";
    this.details = opts.details;
  }
}

/** 展示后端 message；仅网络不可达时前端兜底。 */
export function apiErrorMessage(err: unknown): string {
  if (err instanceof TypeError) {
    return "无法连接服务器，请检查网络或服务是否已启动。";
  }
  if (err instanceof ApiHttpError) {
    return err.detail;
  }
  if (err instanceof Error && err.message.trim()) {
    return err.message;
  }
  return "请求失败，请重试。";
}

/** @deprecated 使用 apiErrorMessage */
export const loginErrorMessage = apiErrorMessage;

async function readApiError(res: Response): Promise<ApiHttpError> {
  let message = "请求失败，请重试。";
  let code = "";
  let errorType = "";
  let traceId = "";
  let details: unknown;
  try {
    const j = await res.json();
    if (j && typeof j === "object") {
      if (typeof j.message === "string" && j.message.trim()) {
        message = j.message;
      } else if (typeof j.detail === "string") {
        message = j.detail;
      } else if (j.detail != null) {
        message = JSON.stringify(j.detail);
      }
      if (typeof j.code === "string") code = j.code;
      if (typeof j.error_type === "string") errorType = j.error_type;
      if (typeof j.trace_id === "string") traceId = j.trace_id;
      details = j.details;
    }
  } catch {
    /* ignore */
  }
  return new ApiHttpError(res.status, message, { code, errorType, traceId, details });
}

/** 供非 `api()` 的 fetch 路径解析错误信封。 */
export async function parseApiError(res: Response): Promise<ApiHttpError> {
  return readApiError(res);
}

export function loadJwt(): string {
  return accessTokenMem;
}

export function saveJwt(token: string): void {
  accessTokenMem = (token || "").trim();
  // 升级迁移：清掉历史持久化的 access，避免 XSS/磁盘残留长期票
  try {
    localStorage.removeItem(JWT_KEY);
  } catch {
    /* ignore */
  }
}

/** 模块加载时：一次性把遗留 ``mc_jwt`` 迁入内存并删除持久化副本。 */
(function migrateLegacyAccessToken(): void {
  try {
    const legacy = (localStorage.getItem(JWT_KEY) || "").trim();
    if (!legacy) return;
    accessTokenMem = legacy;
    localStorage.removeItem(JWT_KEY);
  } catch {
    /* ignore */
  }
})();

/** 清除遗留 ``mc_refresh``；可选迁入内存供一次性换 Cookie。 */
(function migrateLegacyRefreshToken(): void {
  try {
    const legacy = (localStorage.getItem(REFRESH_KEY) || "").trim();
    localStorage.removeItem(REFRESH_KEY);
    if (legacy && !refreshTokenMem) {
      refreshTokenMem = legacy;
    }
  } catch {
    /* ignore */
  }
})();

function purgeRefreshLocalStorage(): void {
  try {
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* ignore */
  }
}

function persistSessionHint(on: boolean): void {
  try {
    if (on) localStorage.setItem(SESSION_HINT_KEY, "1");
    else localStorage.removeItem(SESSION_HINT_KEY);
  } catch {
    /* ignore */
  }
}

function hasDurableSessionHint(): boolean {
  try {
    if (localStorage.getItem(SESSION_HINT_KEY) === "1") return true;
  } catch {
    /* ignore */
  }
  // 兼容尚未写入 mc_session 的旧会话：mc_user 仍在则值得探测 Cookie
  return Boolean(loadUser());
}

/** 登录响应已 Set-Cookie 后调用：丢弃 JS 侧 refresh 副本。 */
export function noteRefreshCookieActive(): void {
  refreshCookieActive = true;
  refreshTokenMem = "";
  persistSessionHint(true);
  purgeRefreshLocalStorage();
}

/** 是否具备 refresh 能力（Cookie、内存交接票，或 F5 后的持久化 hint）。 */
export function hasRefreshSession(): boolean {
  return refreshCookieActive || Boolean(refreshTokenMem) || hasDurableSessionHint();
}

/** 仅返回内存交接票；Cookie 模式为空串（由 credentials 发送）。 */
export function loadRefresh(): string {
  return refreshTokenMem;
}

/**
 * 写入短暂内存交接票（SSO / 邀请）；禁止 localStorage（AUD-2026-02-C）。
 * 空串清除内存票，不关闭已建立的 Cookie 会话标记。
 */
export function saveRefresh(token: string): void {
  purgeRefreshLocalStorage();
  const t = (token || "").trim();
  if (t) {
    refreshTokenMem = t;
    refreshCookieActive = false;
  } else {
    refreshTokenMem = "";
  }
}

export function loadUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function saveUser(user: AuthUser | null): void {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

let refreshInFlight: Promise<boolean> | null = null;
/** 会话世代：登录/清会话时递增，用于忽略过期的 in-flight refresh。 */
let refreshEpoch = 0;

export function clearSession(): void {
  // 作废进行中的 refresh，避免失败回调冲掉后续登录写入的新会话
  refreshEpoch += 1;
  refreshInFlight = null;
  saveJwt("");
  refreshTokenMem = "";
  refreshCookieActive = false;
  persistSessionHint(false);
  purgeRefreshLocalStorage();
  saveUser(null);
  emitSessionChange(null);
}

/**
 * 登录 / SSO / 邀请接受等「整段换新会话」入口调用：
 * 丢弃进行中的旧 refresh，防止其 401 清票或用旧 refresh 覆盖新票。
 */
export function beginAuthSession(): void {
  refreshEpoch += 1;
  refreshInFlight = null;
}

/** 会话变更回调（store 同步 jwt/user，避免 refresh 成功/失败后内存态脱节）。 */
export type SessionSnapshot = { access_token: string; user: AuthUser | null };
type SessionChangeHandler = (session: SessionSnapshot | null) => void;
let sessionChangeHandler: SessionChangeHandler | null = null;

export function bindSessionChange(handler: SessionChangeHandler | null): void {
  sessionChangeHandler = handler;
}

function emitSessionChange(session: SessionSnapshot | null): void {
  try {
    sessionChangeHandler?.(session);
  } catch {
    /* ignore listener errors */
  }
}

/** access 将过期 / 已过期 / 非 access typ（如旧票或 stream 票误存）时需要先 refresh。 */
export function accessTokenNeedsRefresh(
  token: string,
  skewSeconds = 60,
  nowMs: number = Date.now(),
): boolean {
  const raw = (token || "").trim();
  if (!raw) return true;
  try {
    const part = raw.split(".")[1];
    if (!part) return true;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(pad)) as { exp?: number; typ?: string };
    // AP-06 后业务接口要求 typ===access；缺省或其它 typ 一律视为需换票
    if (payload.typ !== "access") return true;
    if (typeof payload.exp !== "number") return true;
    return payload.exp <= nowMs / 1000 + skewSeconds;
  } catch {
    return true;
  }
}

/**
 * 业务请求前确保 access 可用：未过期直接 true；否则单飞 refresh。
 * 无 refresh 且 access 不可用时清会话并返回 false。
 */
export async function ensureFreshSession(): Promise<boolean> {
  const token = loadJwt();
  if (!token && !hasRefreshSession()) return false;
  if (token && !accessTokenNeedsRefresh(token)) return true;
  if (!hasRefreshSession()) {
    clearSession();
    return false;
  }
  return tryRefreshSession();
}

export function loadOrgId(): string {
  try {
    return (localStorage.getItem(ORG_KEY) || "").trim();
  } catch {
    return "";
  }
}

export function saveOrgId(id: string): void {
  try {
    const v = (id || "").trim();
    if (v) localStorage.setItem(ORG_KEY, v);
    else localStorage.removeItem(ORG_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Runner 联调用的平台 Token（可选）；页面 API 优先用 JWT。
 * 未显式写入 localStorage 时返回空串，不注入任何硬编码默认值（AUD-2026-20）。
 */
export function loadRunnerToken(): string {
  try {
    return (localStorage.getItem(RUNNER_TOKEN_KEY) || "").trim();
  } catch {
    return "";
  }
}

/** 用 refresh 换新 access；成功返回 true（Cookie 或内存交接票）。 */
export async function tryRefreshSession(): Promise<boolean> {
  if (!hasRefreshSession()) return false;
  if (refreshInFlight) return refreshInFlight;
  const epoch = refreshEpoch;
  const rt = loadRefresh(); // 可能为空（纯 Cookie）
  let p!: Promise<boolean>;
  p = (async () => {
    try {
      const res = await fetch(resolveApiPath("/auth/refresh"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt || "" }),
      });
      // 登录已换新票：丢弃这次结果，勿清新会话、勿用旧 refresh 覆盖
      if (epoch !== refreshEpoch) {
        const cur = loadJwt();
        return Boolean(cur) && !accessTokenNeedsRefresh(cur);
      }
      if (!res.ok) {
        if (epoch === refreshEpoch && (rt ? loadRefresh() === rt : true)) {
          clearSession();
        }
        return false;
      }
      const out = (await res.json()) as TokenPair;
      if (!out?.access_token) {
        if (epoch === refreshEpoch && (rt ? loadRefresh() === rt : true)) {
          clearSession();
        }
        return false;
      }
      if (
        epoch !== refreshEpoch ||
        (rt && loadRefresh() && loadRefresh() !== rt)
      ) {
        const cur = loadJwt();
        return Boolean(cur) && !accessTokenNeedsRefresh(cur);
      }
      saveJwt(out.access_token);
      // 新 refresh 只进 HttpOnly Cookie，不进 JS（AUD-2026-02-C）
      noteRefreshCookieActive();
      if (out.user) saveUser(out.user);
      emitSessionChange({
        access_token: out.access_token,
        user: out.user || loadUser(),
      });
      return true;
    } catch {
      if (epoch === refreshEpoch && (rt ? loadRefresh() === rt : refreshCookieActive)) {
        return false;
      }
      const cur = loadJwt();
      return Boolean(cur) && !accessTokenNeedsRefresh(cur);
    } finally {
      if (refreshInFlight === p) {
        refreshInFlight = null;
      }
    }
  })();
  refreshInFlight = p;
  return p;
}

export async function postLogout(): Promise<void> {
  const rt = loadRefresh();
  try {
    if (hasRefreshSession()) {
      await fetch(resolveApiPath("/auth/logout"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt || "" }),
      });
    }
  } catch {
    /* ignore */
  } finally {
    clearSession();
  }
}

/** 带当前会话鉴权的原始 fetch；401 时统一刷新一次并重放请求。 */
export async function sessionFetch(
  path: string,
  options: RequestInit = {},
  retried = false,
): Promise<Response> {
  if (!retried && hasRefreshSession() && accessTokenNeedsRefresh(loadJwt())) {
    await ensureFreshSession();
  }
  const headers = new Headers(options.headers || {});
  const bearer = loadJwt();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  const orgId = loadOrgId();
  if (orgId && bearer) headers.set("X-Org-Id", orgId);
  const res = await fetch(resolveApiPath(path), { ...options, headers });
  if (res.status === 401 && !retried && hasRefreshSession() && (await tryRefreshSession())) {
    return sessionFetch(path, options, true);
  }
  return res;
}

export async function api<T>(
  path: string,
  options: RequestInit & {
    token?: string;
    bearer?: string;
    allowRunnerToken?: boolean;
    _retried?: boolean;
  } = {},
): Promise<T> {
  const headers = new Headers(options.headers || {});
  // 未显式指定 bearer 时：过期/非 access typ 先单飞换票，再带新 JWT 发请求
  if (
    options.bearer === undefined &&
    !options._retried &&
    hasRefreshSession() &&
    accessTokenNeedsRefresh(loadJwt()) &&
    !path.includes("/auth/login") &&
    !path.includes("/auth/refresh") &&
    !path.includes("/auth/logout")
  ) {
    await ensureFreshSession();
  }
  const bearer = options.bearer ?? loadJwt();
  if (bearer) {
    headers.set("Authorization", `Bearer ${bearer}`);
  } else if (options.allowRunnerToken || options.token) {
    // 仅显式允许时使用 Runner/运维 Token，避免 JWT 丢失后静默提权
    const runnerTok = options.token ?? loadRunnerToken();
    if (runnerTok) headers.set("X-API-Token", runnerTok);
  }
  const orgId = loadOrgId();
  if (orgId && bearer) {
    headers.set("X-Org-Id", orgId);
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(resolveApiPath(path), { ...options, headers });
  if (
    res.status === 401 &&
    !options._retried &&
    options.bearer === undefined &&
    hasRefreshSession() &&
    !path.includes("/auth/login") &&
    !path.includes("/auth/refresh") &&
    !path.includes("/auth/logout")
  ) {
    const ok = await tryRefreshSession();
    if (ok) {
      return api<T>(path, { ...options, _retried: true });
    }
  }
  if (!res.ok) {
    throw await readApiError(res);
  }
  if (res.status === 204) return null as T;
  const text = await res.text();
  if (!text || text === "null") return null as T;
  return JSON.parse(text) as T;
}

export async function login(username: string, password: string): Promise<TokenPair> {
  const out = await api<TokenPair>("/auth/login", {
    method: "POST",
    bearer: "",
    token: "",
    body: JSON.stringify({ username, password }),
  });
  return out;
}

/** 登录接口不带鉴权头。 */
export async function postIdeHandoffConsume(code: string): Promise<TokenPair> {
  let res: Response;
  try {
    res = await fetch(resolveApiPath("/auth/ide-handoff/consume"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
  } catch (e) {
    throw e instanceof TypeError ? e : new TypeError(String(e));
  }
  if (!res.ok) {
    throw await readApiError(res);
  }
  const out = (await res.json()) as TokenPair;
  noteRefreshCookieActive();
  return out;
}

export async function postLogin(username: string, password: string): Promise<TokenPair> {
  let res: Response;
  try {
    res = await fetch(resolveApiPath("/auth/login"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch (e) {
    throw e instanceof TypeError ? e : new TypeError(String(e));
  }
  if (!res.ok) {
    throw await readApiError(res);
  }
  const out = (await res.json()) as TokenPair;
  // 服务端已 Set-Cookie；Console 不再持久化 refresh（AUD-2026-02-C）
  noteRefreshCookieActive();
  return out;
}

export type Runner = {
  runner_id: string;
  hostname: string;
  version: string;
  capabilities: string[];
  last_heartbeat_at: string | null;
  online: boolean;
  has_token?: boolean;
  org_id?: string;
  project_ids?: string[];
  owner_user_id?: string;
  registration_source?: "ide" | "platform" | "managed";
  device_selection_mode?: "all" | "include";
  selected_device_udids?: string[];
  device_policy_revision?: number;
};

export type RunnerInventoryDevice = {
  udid: string;
  platform: string;
  name: string;
  model: string;
  os_version?: string;
  state?: string;
  backends?: string[];
  health_note?: string;
  registered: boolean;
  busy: boolean;
  reserved: boolean;
  occupancy_kind?: "job" | "reservation" | "";
  occupancy_username?: string;
  occupancy_start_at?: string | null;
  occupancy_end_at?: string | null;
  occupancy_reference?: string;
  occupancy_reason?: string;
  rejection_reason?: string;
};

export type RunnerDeviceInventory = {
  runner_id: string;
  org_id?: string;
  selection_mode: "all" | "include";
  selected_udids: string[];
  policy_revision: number;
  devices: RunnerInventoryDevice[];
};

export type RunnerDeviceSelectionResult = {
  runner_id: string;
  selection_mode: "include";
  selected_udids: string[];
  policy_revision: number;
  registered: string[];
  unregistered: string[];
  rejected: Record<string, string>;
};

export type RunnerProvisionResult = {
  runner_id: string;
  api_token: string;
  org_id: string;
  project_ids: string[];
  command: string;
};

export type ManagedRunnerStatus = {
  enabled: boolean;
  running: boolean;
  managed: boolean;
  pid: number | null;
  runner_id: string;
  started_at: string | null;
  last_error: string;
  exit_code: number | null;
  log_tail: string[];
  cli_command: string;
  note?: string;
};

export type Device = {
  id?: string;
  udid: string;
  platform: string;
  name: string;
  model: string;
  os_version?: string;
  state?: string;
  backends?: string[];
  health_note?: string;
  admin_disabled?: boolean;
  runner_id: string;
  /** 同 UDID 被其它在线 Runner 挂载时的影子节点（看板已折叠，仅供排查） */
  alt_runner_ids?: string[];
  busy?: boolean;
  busy_job_id?: string | null;
  busy_job_name?: string;
  busy_job_status?: string;
  busy_job_project_id?: string;
  busy_kind?: "job" | "reservation" | "";
  /** 人读占用摘要：批跑占用 / 人工预占 */
  occupy_summary?: string;
  registration_source?: "ide" | "platform" | "managed";
  owner_user_id?: string;
  owner_username?: string;
  /** 执行节点是否在心跳窗口内在线；离线时设备可见但不可预占/调度 */
  runner_online?: boolean;
  can_manage?: boolean;
  can_reserve?: boolean;
  reservation_id?: string | null;
  reservation_user_id?: string;
  reservation_username?: string;
  /** 该设备是否已有进行中的远控会话（pending/ready/connected） */
  remote_session_active?: boolean;
  reservation_reason?: string;
  /** 解析自 reason 前缀：手工调试 / 远控预留 / 演示联调 */
  reservation_purpose?: string;
  reservation_expires_at?: string | null;
  reservation_remaining_seconds?: number;
  can_release_reservation?: boolean;
};

export type Job = {
  id: string;
  name: string;
  status: string;
  project_dir: string;
  artifact_id?: string | null;
  app_build_id?: string | null;
  app_build_name?: string;
  app_version_name?: string;
  app_version_code?: number;
  app_package_id?: string;
  project_id?: string;
  platform: string;
  backend_mode?: string;
  /** platform=web：selenium|playwright（与 backend_mode 浏览器类型独立） */
  web_engine?: string;
  runner_id: string | null;
  parent_job_id?: string | null;
  webhook_url?: string;
  /** enqueue / 创建 Job 软提示（缺 Binding 等），不影响入队成功 */
  warnings?: string[];
};

export type Report = {
  report_path: string;
  passed: number;
  failed: number;
  total: number;
  duration_ms: number;
  summary: string;
  job_id?: string;
  stored?: boolean;
  artifact_id?: string | null;
  artifact_name?: string;
  app_build_id?: string | null;
  app_build_name?: string;
  app_version_name?: string;
  app_platform?: string;
  job_name?: string;
  project_id?: string;
  platform?: string;
};

export type Artifact = {
  id: string;
  name: string;
  filename: string;
  size_bytes: number;
  uploaded_by: string;
  created_at?: string | null;
  project_id?: string;
  manifest_status?: string;
  manifest_version?: string;
  manifest_warnings?: string[];
  manifest_errors?: string[];
};

export type AppBuild = {
  id: string;
  name: string;
  filename: string;
  platform: string;
  version_name: string;
  version_code: number;
  size_bytes: number;
  sha256: string;
  package_id: string;
  main_activity: string;
  uploaded_by?: string;
  created_at?: string | null;
  project_id?: string;
  reused?: boolean;
};

export type AuditLog = {
  id: string;
  action: string;
  actor: string;
  actor_kind: string;
  resource_type: string;
  resource_id: string;
  org_id?: string;
  detail: string;
  created_at?: string | null;
};
