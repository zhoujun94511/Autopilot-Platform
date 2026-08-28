/**
 * API 路径常量（默认与后端 bootstrap 一致；运行时以 loadPlatformBootstrap 为准）。
 * 业务代码应优先使用 apiPath()，避免手写 /api/v1。
 */
import { apiPath, apiPrefix, getPlatformBootstrap } from "./bootstrap";

export { apiPath, apiPrefix, getPlatformBootstrap };

export const EP = {
  health: () => getPlatformBootstrap().endpoints.health || "/health",
  login: () => getPlatformBootstrap().endpoints.login || apiPath("/auth/login"),
  refresh: () => getPlatformBootstrap().endpoints.refresh || apiPath("/auth/refresh"),
  logout: () => apiPath("/auth/logout"),
  me: () => getPlatformBootstrap().endpoints.me || apiPath("/auth/me"),
  opsConfig: () => getPlatformBootstrap().endpoints.ops_config || apiPath("/ops/config"),
  bootstrap: () => getPlatformBootstrap().endpoints.bootstrap || apiPath("/public/bootstrap"),
  openapi: () => getPlatformBootstrap().endpoints.openapi || "/docs",
} as const;
