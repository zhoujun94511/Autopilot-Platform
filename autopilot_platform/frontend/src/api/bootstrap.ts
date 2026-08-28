/** Platform 公开 Bootstrap（后端下发基址与 API 路径真源）。 */

export type PlatformBootstrap = {
  schema_version: string;
  platform_base_url: string;
  api_prefix: string;
  web_dev_port: number;
  config_priority: string;
  endpoints: Record<string, string>;
  runner: { module: string; cli_command: string };
  flags: {
    design_webhook_configured?: boolean;
    managed_runner_allowed?: boolean;
    metrics_enabled?: boolean;
    production?: boolean;
    /** AUD-2026-06：仍存在开发默认凭据（不回显密钥） */
    insecure_defaults?: boolean;
    /** 非 loopback 绑定 */
    bind_exposed?: boolean;
  };
};

const FALLBACK: PlatformBootstrap = {
  schema_version: "1",
  platform_base_url: "",
  api_prefix: "/api/v1",
  web_dev_port: 5173,
  config_priority: "runtime_json > env > code_default",
  endpoints: {
    health: "/health",
    metrics: "/metrics",
    openapi: "/docs",
    bootstrap: "/api/v1/public/bootstrap",
    login: "/api/v1/auth/login",
    refresh: "/api/v1/auth/refresh",
    me: "/api/v1/auth/me",
    ops_config: "/api/v1/ops/config",
    runners_managed: "/api/v1/runners/managed",
  },
  runner: {
    module: "autopilot_platform.runner",
    cli_command:
      "python -m autopilot_platform.runner --server <platform-url> --token-env MC_RUNNER_TOKEN",
  },
  flags: {},
};

let cached: PlatformBootstrap | null = null;
let loadPromise: Promise<PlatformBootstrap> | null = null;

export function getPlatformBootstrap(): PlatformBootstrap {
  return cached || FALLBACK;
}

export function apiPrefix(): string {
  return (getPlatformBootstrap().api_prefix || "/api/v1").replace(/\/+$/, "");
}

/** 相对路径 API（同源 / Vite 代理）；suffix 可带或不带 leading slash。 */
export function apiPath(suffix: string): string {
  const raw = (suffix || "").trim();
  if (!raw) return apiPrefix();
  if (raw.startsWith("/api/")) {
    const rest = raw.replace(/^\/api\/v\d+/, "") || "";
    return `${apiPrefix()}${rest.startsWith("/") ? rest : `/${rest}`}`;
  }
  const sub = raw.startsWith("/") ? raw : `/${raw}`;
  return `${apiPrefix()}${sub}`;
}

/** 绝对 Platform URL（OpenAPI、外链、复制给 IDE）。 */
export function absolutePlatformUrl(path: string): string {
  const base = (getPlatformBootstrap().platform_base_url || "").replace(/\/+$/, "");
  const p = (path || "").startsWith("/") ? path : `/${path || ""}`;
  if (base) return `${base}${p}`;
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}${p}`;
  }
  return p;
}

/**
 * 远控 WebSocket 基址。
 * 开发环境（Vite :5173）与 HTTP API 一致走同源 /api 代理（vite.config ws:true），
 * 避免页面在 5173、Platform 在 8000 时跨端口 WS 连不上而永远 HTTP poll。
 * 生产/同端口部署时再按 bootstrap.platform_base_url 直连。
 */
export function remoteWebSocketUrl(path: string, params?: URLSearchParams): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const query = params?.toString() ? `?${params.toString()}` : "";

  if (typeof window !== "undefined") {
    const devPort = String(getPlatformBootstrap().web_dev_port || 5173);
    const onDevServer =
      import.meta.env.DEV || window.location.port === devPort;
    if (onDevServer) {
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${scheme}//${window.location.host}${normalized}${query}`;
    }
  }

  const base = (getPlatformBootstrap().platform_base_url || "").replace(/\/+$/, "");
  const pageOrigin =
    typeof window !== "undefined" && window.location?.origin
      ? window.location.origin.replace(/\/+$/, "")
      : "";
  if (base && pageOrigin && base !== pageOrigin) {
    const wsBase = base.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
    return `${wsBase}${normalized}${query}`;
  }
  if (typeof window === "undefined") {
    return `ws://127.0.0.1${normalized}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${normalized}${query}`;
}

export function runnerCliFallback(): string {
  return getPlatformBootstrap().runner?.cli_command || FALLBACK.runner.cli_command;
}

export async function loadPlatformBootstrap(force = false): Promise<PlatformBootstrap> {
  if (cached && !force) return cached;
  if (loadPromise && !force) return loadPromise;
  loadPromise = (async () => {
    try {
      const res = await fetch(apiPath("/public/bootstrap"));
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as PlatformBootstrap;
      if (data?.api_prefix) {
        cached = { ...FALLBACK, ...data, endpoints: { ...FALLBACK.endpoints, ...data.endpoints } };
        return cached;
      }
    } catch {
      /* 离线/启动中：使用 FALLBACK，相对路径仍可工作 */
    }
    cached = { ...FALLBACK };
    return cached;
  })();
  return loadPromise;
}
