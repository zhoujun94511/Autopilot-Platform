/**
 * 批跑 / 入队 / 计划共用的运行目标选项与切平台副作用。
 *
 * 浏览器类型占用 backend_mode（与 JobCreate 一致）；Web 引擎走独立 web_engine。
 * HTTP 的 backend_mode 承载 api_env.yaml profile（auto=用例内 api_env_use）。
 */

export type RunTargetOption = { value: string; label: string };

export const PLATFORM_OPTIONS: RunTargetOption[] = [
  { value: "android", label: "安卓" },
  { value: "ios", label: "苹果" },
  { value: "web", label: "网页" },
  { value: "http", label: "接口" },
];

export const WEB_BROWSER_OPTIONS: RunTargetOption[] = [
  { value: "auto", label: "默认（用例内「浏览器打开」指定，通常 Chrome）" },
  { value: "chrome", label: "Chrome" },
  { value: "edge", label: "Edge" },
  { value: "firefox", label: "Firefox" },
  { value: "headless", label: "Chrome Headless" },
];

export const WEB_ENGINE_OPTIONS: RunTargetOption[] = [
  { value: "selenium", label: "Selenium（默认主力）" },
  { value: "playwright", label: "Playwright（可选增强）" },
];

export const MOBILE_BACKEND_OPTIONS: RunTargetOption[] = [
  { value: "auto", label: "自动（按平台与设备能力选择，推荐）" },
  { value: "uia2", label: "Android UiAutomator2" },
  { value: "wda", label: "iOS WDA 直连（Win / Linux）" },
  { value: "appium", label: "Appium（Mac iOS / Android）" },
];

const WEB_BROWSER_VALUES = new Set(["chrome", "edge", "firefox", "headless"]);
const MOBILE_BACKEND_FORCED = new Set(["uia2", "wda", "appium"]);

export const DEVICELESS_PLATFORMS = new Set(["web", "http"]);

export function isDevicelessPlatform(platform: string): boolean {
  return DEVICELESS_PLATFORMS.has((platform || "").toLowerCase());
}

export function isHttpPlatform(platform: string): boolean {
  return (platform || "").toLowerCase() === "http";
}

export function isWebPlatform(platform: string): boolean {
  return (platform || "").toLowerCase() === "web";
}

/** 批跑表单 / 入队 / 计划共用的执行目标字段。 */
export type RunTargetModel = {
  platform: string;
  device_udids: string;
  backend_mode: string;
  web_engine: string;
  wda_bundle: string;
  preferred_runner_id: string;
  parallel: boolean;
  parallel_workers: number;
  app_build_id?: string;
};

/** 提交 Job / 计划前剥移动字段；与后端 apply_deviceless_run_target 对齐。 */
export function stripDevicelessSubmitPayload(
  platform: string,
  body: Record<string, unknown>,
): void {
  if (!isDevicelessPlatform(platform)) return;
  body.device_udids = [];
  body.parallel = false;
  body.parallel_workers = 0;
  body.wda_bundle = "";
  delete body.app_build_id;
  if (!isWebPlatform(platform)) {
    body.web_engine = "selenium";
  }
}

export function applyPlatformSideEffects(
  form: RunTargetModel,
  platform: string,
): void {
  const p = (platform || "").toLowerCase();
  const mode = (form.backend_mode || "auto").toLowerCase();
  if (isDevicelessPlatform(p)) {
    form.device_udids = "";
    if ("app_build_id" in form) form.app_build_id = "";
    form.parallel = false;
    form.parallel_workers = 0;
    form.wda_bundle = "";
    if (p === "web") {
      form.web_engine = form.web_engine || "selenium";
      if (MOBILE_BACKEND_FORCED.has(mode)) {
        form.backend_mode = "auto";
      }
      return;
    }
    form.web_engine = "selenium";
    if (MOBILE_BACKEND_FORCED.has(mode) || WEB_BROWSER_VALUES.has(mode)) {
      form.backend_mode = "auto";
    }
    return;
  }
  if (WEB_BROWSER_VALUES.has(mode) || (!MOBILE_BACKEND_FORCED.has(mode) && mode !== "auto")) {
    form.backend_mode = "auto";
  }
}
