/**
 * 管理台全局提示（替代 window.alert / confirm / prompt）。
 * App.vue 挂载 <AppNotifyHost /> 后即可在任意模块调用。
 *
 * 禁止直接调用浏览器原生弹框：`alert` / `confirm` / `prompt` 在嵌入 WebView、
 * 远控叠层、非前台标签上表现不一致（可能被拦截、无样式、挡住错误层）。
 * 确认 / 单字段输入 / 敏感复制一律走本模块，由 AppNotifyHost 渲染 ApModal。
 *
 * ## 通知分层约定（勿推倒重来）
 *
 * 1. **瞬时交互**（确认 / 输入 / 敏感复制）→ 只用本模块
 *    `confirmDialog` / `promptDialog` / `showCopyDialog`
 *    `promptDialog` 只服务单字段输入，禁止串联多次来凑一个表单：一个动作要
 *    采集多个字段时，做专用表单弹窗（`ApModal` + 独立 composable，参考
 *    `useReserveDialog`），否则用户被迫多次上下文切换且无法回退改上一步。
 *
 * 2. **无表单上下文的列表/工具动作结果** → `notify(text, kind)`
 *    例：取消/重试任务、删制品/应用资源、设备占用释放、用户启用禁用删除、
 *    ACL 撤销、purge、Runner Token 相关。
 *    成功用 `"success"`，失败用 `"error"`，警告用 `"warn"`，提示用 `"info"`。
 *    **默认只弹出 warn/error**（成功/info 调用可保留语义，不打扰）。
 *    某面板要成功 Toast：`createNotifier({ success: true })`；单次强制：
 *    `notify(text, "success", { toast: true })`。`toast` 是 `notify` 的别名。
 *    最新在上，最多 4 条；success/info 约 2.8s，warn/error 约 5s，悬停暂停。
 *
 * 3. **绑定当前表单的校验与结果** → 面板内联 `xxxMsg`（留在表单旁）
 *    例：`jobMsg`（批跑创建）、`scheduleMsg`、`artMsg`/`appBuildMsg`（上传）、
 *    `userMsg`（创建用户表单）、`shareMsg`、`opsConfigMsg`、Design 面板 `notice`/`error`。
 *    多行 warning、需对照表单修改的错误优先内联，不要塞 Toast。
 *
 * 4. **全局数据层故障** → `shell.error`（App 顶栏横幅）
 *    例：轮询 / Tab 刷新失败。与 Toast 分工：横幅可持续可见。
 *
 * 5. **情境状态** → Banner / Dashboard alert-strip（不是通知通道）
 *    例：缺项目、只读项目、概览「需关注」。
 *
 * 判定口诀：用户还要不要对着表单改？要 → 内联 msg；不要 → notify。
 */
import { ref, shallowRef } from "vue";

export type NotifyKind = "info" | "success" | "error" | "warn";

/** 各 kind 是否弹出 Toast。组件用 createNotifier 覆盖，单次用 { toast }。 */
export type NotifyKindPolicy = Record<NotifyKind, boolean>;

export type NotifyOptions = {
  /** true 强制弹出，false 强制不弹，覆盖策略 */
  toast?: boolean;
};

export type Notifier = (
  text: string,
  kind?: NotifyKind,
  opts?: NotifyOptions,
) => void;

/** 默认只弹警告/失败；成功与 info 保留调用语义但不打扰。 */
export const DEFAULT_TOAST_KINDS: NotifyKindPolicy = {
  success: false,
  info: false,
  warn: true,
  error: true,
};

let runtimePolicy: Partial<NotifyKindPolicy> = {};

export function setNotifyPolicy(policy: Partial<NotifyKindPolicy>) {
  runtimePolicy = { ...policy };
}

export function resetNotifyPolicy() {
  runtimePolicy = {};
}

function mergePolicy(local?: Partial<NotifyKindPolicy>): NotifyKindPolicy {
  return { ...DEFAULT_TOAST_KINDS, ...runtimePolicy, ...local };
}

function shouldToast(kind: NotifyKind, policy: NotifyKindPolicy, opts?: NotifyOptions): boolean {
  if (typeof opts?.toast === "boolean") return opts.toast;
  return policy[kind];
}

export type ToastItem = {
  id: number;
  text: string;
  kind: NotifyKind;
};

type ConfirmState = {
  text: string;
  title: string;
  okText: string;
  cancelText: string;
  danger: boolean;
  resolve: (ok: boolean) => void;
};

type PromptState = {
  text: string;
  title: string;
  defaultValue: string;
  password: boolean;
  placeholder: string;
  resolve: (value: string | null) => void;
};

type CopyState = {
  title: string;
  text: string;
  value: string;
  resolve: () => void;
};

let seq = 1;

export const notifyToasts = ref<ToastItem[]>([]);
export const notifyConfirm = shallowRef<ConfirmState | null>(null);
export const notifyPrompt = shallowRef<PromptState | null>(null);
export const notifyCopy = shallowRef<CopyState | null>(null);

/** 按 kind 停留：成功/提示短、警告/失败更长（对标 Arco / Ant Design）。 */
export const TOAST_MS: Record<NotifyKind, number> = {
  success: 2800,
  info: 2800,
  warn: 5000,
  error: 5000,
};

export const TOAST_MAX = 4;

const KIND_SET: ReadonlySet<NotifyKind> = new Set(["info", "success", "error", "warn"]);

type ToastTimer = {
  handle: ReturnType<typeof window.setTimeout>;
  remain: number;
  started: number;
  paused: boolean;
};

const timers = new Map<number, ToastTimer>();

function asKind(kind: string): NotifyKind {
  if (kind === "bad") return "error";
  if (kind === "ok") return "success";
  return KIND_SET.has(kind as NotifyKind) ? (kind as NotifyKind) : "info";
}

function clearTimer(id: number) {
  const t = timers.get(id);
  if (!t) return;
  window.clearTimeout(t.handle);
  timers.delete(id);
}

function armTimer(id: number, ms: number) {
  clearTimer(id);
  const handle = window.setTimeout(() => dismissToast(id), ms);
  timers.set(id, { handle, remain: ms, started: Date.now(), paused: false });
}

export function pauseToast(id: number) {
  const t = timers.get(id);
  if (!t || t.paused) return;
  window.clearTimeout(t.handle);
  t.remain = Math.max(0, t.remain - (Date.now() - t.started));
  t.paused = true;
}

export function resumeToast(id: number) {
  const t = timers.get(id);
  if (!t || !t.paused) return;
  if (t.remain <= 0) {
    dismissToast(id);
    return;
  }
  t.paused = false;
  t.started = Date.now();
  t.handle = window.setTimeout(() => dismissToast(id), t.remain);
}

function enqueueToast(text: string, kind: NotifyKind) {
  const id = seq++;
  const stacked = [{ id, text, kind }, ...notifyToasts.value];
  for (const item of stacked.slice(TOAST_MAX)) {
    clearTimer(item.id);
  }
  notifyToasts.value = stacked.slice(0, TOAST_MAX);
  armTimer(id, TOAST_MS[kind]);
}

function pushToast(
  text: string,
  kind: NotifyKind | string,
  policy: NotifyKindPolicy,
  opts?: NotifyOptions,
) {
  const resolved = asKind(kind);
  if (!shouldToast(resolved, policy, opts)) return;
  enqueueToast(text, resolved);
}

/** 某面板要打开成功 Toast：createNotifier({ success: true })。 */
export function createNotifier(policy?: Partial<NotifyKindPolicy>): Notifier {
  return (text, kind = "info", opts) => {
    pushToast(text, kind, mergePolicy(policy), opts);
  };
}

/** 在 setup 里按面板覆盖 kind：const { notify } = useNotify({ success: true }) */
export function useNotify(policy?: Partial<NotifyKindPolicy>) {
  const notifyFn = createNotifier(policy);
  return { notify: notifyFn, toast: notifyFn };
}

export const toast: Notifier = (text, kind = "info", opts) => {
  pushToast(text, kind, mergePolicy(), opts);
};

export function dismissToast(id: number) {
  clearTimer(id);
  notifyToasts.value = notifyToasts.value.filter((t) => t.id !== id);
}

/** 成功/失败反馈（无表单上下文的瞬时结果；见文件头分层约定） */
export const notify: Notifier = toast;

export function confirmDialog(
  text: string,
  opts?: {
    title?: string;
    okText?: string;
    cancelText?: string;
    danger?: boolean;
  },
): Promise<boolean> {
  return new Promise((resolve) => {
    notifyConfirm.value = {
      text,
      title: opts?.title || "确认",
      okText: opts?.okText || "确定",
      cancelText: opts?.cancelText || "取消",
      danger: Boolean(opts?.danger),
      resolve: (ok) => {
        notifyConfirm.value = null;
        resolve(ok);
      },
    };
  });
}

export function promptDialog(
  text: string,
  opts?: {
    title?: string;
    defaultValue?: string;
    password?: boolean;
    placeholder?: string;
  },
): Promise<string | null> {
  return new Promise((resolve) => {
    notifyPrompt.value = {
      text,
      title: opts?.title || "输入",
      defaultValue: opts?.defaultValue ?? "",
      password: Boolean(opts?.password),
      placeholder: opts?.placeholder || "",
      resolve: (value) => {
        notifyPrompt.value = null;
        resolve(value);
      },
    };
  });
}

/** 展示需立即复制的敏感值（如 Runner Token） */
export function showCopyDialog(
  value: string,
  opts?: { title?: string; text?: string },
): Promise<void> {
  return new Promise((resolve) => {
    notifyCopy.value = {
      title: opts?.title || "请复制保存",
      text: opts?.text || "以下内容仅显示一次，请立即复制。",
      value,
      resolve: () => {
        notifyCopy.value = null;
        resolve();
      },
    };
  });
}
