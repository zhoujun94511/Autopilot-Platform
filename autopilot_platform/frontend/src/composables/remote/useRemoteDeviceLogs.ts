import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { apiPath } from "../../api/bootstrap";
import {
  apiClearRemoteDeviceLogs,
  apiCreateDeviceLogStreamToken,
} from "../../api/remote";
import { remoteDialogState } from "../useRemoteSession";
import { confirmDialog, notify } from "../useNotify";

export type DeviceLogLine = {
  k: number;
  raw: string;
  lvl: string;
  time: string;
  tag: string;
  msg: string;
};

export const ANDROID_LEVELS = [
  { value: "V", label: "详细 · Verbose (V)", hint: "全部输出" },
  { value: "D", label: "调试 · Debug (D)", hint: "调试及以上" },
  { value: "I", label: "信息 · Info (I)", hint: "信息及以上（默认）" },
  { value: "W", label: "警告 · Warning (W)", hint: "警告及以上" },
  { value: "E", label: "错误 · Error (E)", hint: "错误及以上" },
  { value: "F", label: "致命 · Fatal (F)", hint: "仅致命" },
] as const;

export const IOS_LEVELS = [
  { value: "", label: "全部级别" },
  { value: "Default", label: "默认 · Default" },
  { value: "Info", label: "信息 · Info" },
  { value: "Debug", label: "调试 · Debug" },
  { value: "Notice", label: "通知 · Notice" },
  { value: "Error", label: "错误 · Error" },
  { value: "Fault", label: "故障 · Fault" },
] as const;

const IOS_LEVEL_CSS: Record<string, string> = {
  Default: "V",
  Debug: "D",
  Info: "I",
  Notice: "W",
  Error: "E",
  Fault: "F",
};

const MAX_LINES = 3000;
const FLUSH_MS = 80;
const RENDER_CAP = 600;
const MAX_RECONNECT = 4;
const RECONNECT_MS = 2000;
const TS_RE = /^[A-Z][a-z]{2}\s+\d+\s+[\d:]+\s+\S+\s+/;
const PROC_RE = /(?:^|\s)([A-Za-z0-9_.\-]+)(?:\([^)]*\))?\[\d+\]/;
const ANDROID_THREADTIME =
  /^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(\S+)\s*:\s*(.*)$/;
const IOS_LEVEL_PREFIX = /^<(\w+)>\s*(.*)$/;

function detectLevel(raw: string): string {
  const android = raw.match(/\s([VDIWEF])\s/);
  if (android) return android[1];
  const named = raw.match(/<(\w+)>/);
  if (named && IOS_LEVEL_CSS[named[1]]) return IOS_LEVEL_CSS[named[1]];
  return "I";
}

function procOf(line: string): string {
  const match = line.match(PROC_RE);
  return match ? match[1] : "";
}

function parseLine(raw: string, android: boolean): Omit<DeviceLogLine, "k"> {
  if (android) {
    const match = raw.match(ANDROID_THREADTIME);
    if (match) {
      return {
        raw,
        time: match[1],
        lvl: match[4],
        tag: match[5],
        msg: match[6],
      };
    }
    return { raw, time: "", lvl: detectLevel(raw), tag: "", msg: raw };
  }
  const leveled = raw.match(IOS_LEVEL_PREFIX);
  const body = leveled ? leveled[2] : raw;
  const stamp = body.match(TS_RE);
  return {
    raw,
    time: stamp ? stamp[0].trim() : "",
    lvl: leveled && IOS_LEVEL_CSS[leveled[1]] ? IOS_LEVEL_CSS[leveled[1]] : detectLevel(raw),
    tag: procOf(body),
    msg: stamp ? body.slice(stamp[0].length) : body,
  };
}

export function useRemoteDeviceLogs(platform: string, readonly = false) {
  const android = platform !== "ios";
  const level = ref(android ? "I" : "");
  const tag = ref("");
  const grep = ref("");
  const regexOn = ref(false);
  const proc = ref("");
  const wrap = ref(true);
  const showTs = ref(true);
  const streaming = ref(false);
  const autoscroll = ref(true);
  const atBottom = ref(true);
  const error = ref("");
  const status = ref("正在连接…");
  const copied = ref(false);
  const searchErr = ref(false);
  const lines = shallowRef<DeviceLogLine[]>([]);
  const viewEl = ref<HTMLElement | null>(null);
  const sessionReady = computed(() => Boolean(remoteDialogState.value?.session?.id));
  const prefsKey = android ? "remote-logcat-prefs" : "remote-syslog-prefs";

  try {
    const saved = JSON.parse(localStorage.getItem(prefsKey) || "{}") as Record<string, unknown>;
    if (android && typeof saved.level === "string" && ANDROID_LEVELS.some((item) => item.value === saved.level)) {
      level.value = saved.level;
    }
    if (!android && typeof saved.level === "string" && IOS_LEVELS.some((item) => item.value === saved.level)) {
      level.value = saved.level;
    }
    if (typeof saved.wrap === "boolean") wrap.value = saved.wrap;
    if (typeof saved.showTs === "boolean") showTs.value = saved.showTs;
    if (typeof saved.regexOn === "boolean") regexOn.value = saved.regexOn;
    if (typeof saved.autoscroll === "boolean") autoscroll.value = saved.autoscroll;
  } catch {
    /* ignore */
  }

  watch([level, wrap, showTs, regexOn, autoscroll], () => {
    try {
      localStorage.setItem(
        prefsKey,
        JSON.stringify({
          level: level.value,
          wrap: wrap.value,
          showTs: showTs.value,
          regexOn: regexOn.value,
          autoscroll: autoscroll.value,
        }),
      );
    } catch {
      /* ignore */
    }
  });

  let pending: DeviceLogLine[] = [];
  let buffer: DeviceLogLine[] = [];
  let seq = 0;
  let es: EventSource | null = null;
  let flushTimer: number | null = null;
  let reconnectTimer = 0;
  let reconnects = 0;
  let openedAt = 0;
  let stoppedByUs = false;
  let mounted = true;
  let copyTimer = 0;

  const visibleLines = computed(() => {
    const needle = grep.value.trim();
    const procNeedle = proc.value.trim().toLowerCase();
    searchErr.value = false;
    let regex: RegExp | null = null;
    if (needle && regexOn.value) {
      try {
        regex = new RegExp(needle, "i");
      } catch {
        searchErr.value = true;
      }
    }
    const out: DeviceLogLine[] = [];
    const all = lines.value;
    for (let i = all.length - 1; i >= 0 && out.length < RENDER_CAP; i -= 1) {
      const row = all[i];
      if (!android && level.value && !row.raw.includes(`<${level.value}>`)) continue;
      if (procNeedle && !procOf(row.raw).toLowerCase().includes(procNeedle)) continue;
      if (needle) {
        if (regexOn.value) {
          if (!regex || !regex.test(row.raw)) continue;
        } else if (!row.raw.toLowerCase().includes(needle.toLowerCase())) {
          continue;
        }
      }
      out.push(row);
    }
    return out.reverse();
  });

  const totalCount = computed(() => lines.value.length);
  const visibleCount = computed(() => visibleLines.value.length);

  function displayMsg(row: DeviceLogLine): string {
    if (android || showTs.value) return row.raw;
    return row.raw.replace(TS_RE, "");
  }

  function publish() {
    lines.value = buffer.slice();
  }

  function scrollToBottom() {
    void nextTick(() => {
      const el = viewEl.value;
      if (el && autoscroll.value) el.scrollTop = el.scrollHeight;
    });
  }

  function flush() {
    if (!pending.length) return;
    buffer = buffer.concat(pending);
    pending = [];
    if (buffer.length > MAX_LINES) buffer = buffer.slice(buffer.length - MAX_LINES);
    publish();
    if (autoscroll.value) scrollToBottom();
  }

  function startFlush() {
    if (flushTimer != null) return;
    flushTimer = window.setInterval(flush, FLUSH_MS);
  }

  function stopFlush() {
    if (flushTimer != null) {
      window.clearInterval(flushTimer);
      flushTimer = null;
    }
    flush();
  }

  function closeSource() {
    if (es) {
      try {
        es.close();
      } catch {
        /* ignore */
      }
      es = null;
    }
  }

  function sessionId(): string {
    return remoteDialogState.value?.session?.id || "";
  }

  function deviceLabel(): string {
    const session = remoteDialogState.value?.session;
    return (session?.udid || session?.device_id || "device").replace(/[^\w.-]+/g, "_");
  }

  function stopStream() {
    stoppedByUs = true;
    window.clearTimeout(reconnectTimer);
    reconnectTimer = 0;
    closeSource();
    stopFlush();
    streaming.value = false;
    if (mounted) status.value = "已暂停";
  }

  async function openStream() {
    closeSource();
    window.clearTimeout(reconnectTimer);
    reconnectTimer = 0;
    if (!mounted) return;
    const sid = sessionId();
    if (!sid) {
      error.value = "";
      streaming.value = false;
      status.value = "等待远控会话";
      return;
    }
    error.value = "";
    status.value = "正在连接…";
    stoppedByUs = false;
    try {
      const tokenOut = await apiCreateDeviceLogStreamToken(sid);
      if (!mounted || stoppedByUs) return;
      const token = (tokenOut.access_token || "").trim();
      if (!token) throw new Error("短时流令牌为空");
      const params = new URLSearchParams({
        access_token: token,
        level: android ? level.value || "I" : "I",
      });
      if (android && tag.value.trim()) params.set("tag", tag.value.trim());
      const url = `${apiPath(`/device-remote-sessions/${encodeURIComponent(sid)}/logs/stream`)}?${params}`;
      es = new EventSource(url);
      streaming.value = true;
      es.onopen = () => {
        if (!mounted) {
          closeSource();
          return;
        }
        error.value = "";
        status.value = "实时";
        openedAt = performance.now();
      };
      es.onmessage = (ev) => {
        const raw = String(ev.data || "");
        if (!raw) return;
        seq += 1;
        pending.push({ k: seq, ...parseLine(raw, android) });
      };
      es.onerror = () => {
        if (stoppedByUs || !mounted) return;
        closeSource();
        stopFlush();
        streaming.value = false;
        const ranLong = openedAt > 0 && performance.now() - openedAt > 15_000;
        if (ranLong) reconnects = 0;
        if (reconnects < MAX_RECONNECT) {
          reconnects += 1;
          error.value = "";
          status.value = `重连中（${reconnects}/${MAX_RECONNECT}）`;
          reconnectTimer = window.setTimeout(() => {
            if (mounted && !stoppedByUs) void openStream();
          }, RECONNECT_MS);
          return;
        }
        error.value = "日志流已断开，点「继续」再开流";
        status.value = "已暂停";
      };
      startFlush();
    } catch (cause) {
      streaming.value = false;
      if (!mounted) return;
      error.value = cause instanceof Error ? cause.message : "无法开始日志流";
      status.value = "未开始";
    }
  }

  async function toggleStream() {
    if (streaming.value) stopStream();
    else {
      reconnects = 0;
      await openStream();
    }
  }

  function clearLocal() {
    pending = [];
    buffer = [];
    publish();
  }

  async function clearAll() {
    const ok = await confirmDialog(
      android && !readonly
        ? "清空本页显示，并在设备上执行 logcat -c？设备侧缓冲也会被清掉。"
        : "清空本页日志缓冲？",
      { title: "清空日志", okText: "清空", danger: true },
    );
    if (!ok) return;
    clearLocal();
    if (!android || readonly) return;
    const sid = sessionId();
    if (!sid) return;
    try {
      await apiClearRemoteDeviceLogs(sid);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "清空设备日志失败";
    }
  }

  function save() {
    const rows = android
      ? visibleLines.value.map((row) => row.raw)
      : buffer.map((row) => row.raw);
    const blob = new Blob([rows.join("\n")], { type: "text/plain;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const id = deviceLabel();
    a.href = href;
    a.download = android
      ? `logcat-${id}-${stamp}.txt`
      : `syslog-${id.slice(0, 8)}-${Date.now()}.log`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  }

  async function copyLines() {
    const selected = window.getSelection?.()?.toString().trim() || "";
    const text =
      selected || visibleLines.value.map((row) => row.raw).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      copied.value = true;
      window.clearTimeout(copyTimer);
      copyTimer = window.setTimeout(() => {
        copied.value = false;
      }, 1500);
    } catch {
      error.value = "浏览器拒绝写入剪贴板";
      notify("复制失败，请检查浏览器剪贴板权限", "error");
    }
  }

  function onScroll() {
    const el = viewEl.value;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    atBottom.value = bottom;
    if (!bottom && autoscroll.value) autoscroll.value = false;
    if (bottom && !autoscroll.value) autoscroll.value = true;
  }

  function jumpBottom() {
    autoscroll.value = true;
    atBottom.value = true;
    scrollToBottom();
  }

  watch([level, tag], () => {
    if (!android || !mounted || !streaming.value) return;
    pending = [];
    buffer = [];
    publish();
    void openStream();
  });

  watch(
    () => remoteDialogState.value?.session?.id || "",
    (sid, previous) => {
      if (!mounted || !sid || sid === previous) return;
      reconnects = 0;
      void openStream();
    },
  );

  onMounted(() => {
    mounted = true;
    reconnects = 0;
    void openStream();
  });

  onBeforeUnmount(() => {
    mounted = false;
    window.clearTimeout(copyTimer);
    stopStream();
  });

  return {
    android,
    androidLevels: ANDROID_LEVELS,
    iosLevels: IOS_LEVELS,
    sessionReady,
    level,
    tag,
    grep,
    regexOn,
    proc,
    wrap,
    showTs,
    streaming,
    autoscroll,
    atBottom,
    error,
    status,
    copied,
    searchErr,
    viewEl,
    visibleLines,
    totalCount,
    visibleCount,
    displayMsg,
    toggleStream,
    clearAll,
    save,
    copyLines,
    onScroll,
    jumpBottom,
  };
}
