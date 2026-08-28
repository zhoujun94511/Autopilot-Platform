<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { apiErrorMessage, parseApiError, sessionFetch } from "../api";

const props = defineProps<{ jobId: string }>();
const emit = defineEmits<{ close: [] }>();

const logText = ref("");
const status = ref("加载中…");
const preEl = ref<HTMLElement | null>(null);
const autoScroll = ref(true);
let es: EventSource | null = null;
let loadedBytes = 0;
let errorCount = 0;
let stoppedByUs = false;
const MAX_LOG_CHARS = 800_000;
const MAX_SSE_ERRORS = 3;

function scrollToBottom() {
  if (!autoScroll.value) return;
  void nextTick(() => {
    if (preEl.value) preEl.value.scrollTop = preEl.value.scrollHeight;
  });
}

function stopStream() {
  stoppedByUs = true;
  if (es) {
    es.close();
    es = null;
  }
}

function appendLog(chunk: string) {
  logText.value += chunk;
  if (logText.value.length > MAX_LOG_CHARS) {
    logText.value = logText.value.slice(-MAX_LOG_CHARS);
  }
}

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value;
  if (autoScroll.value) {
    scrollToBottom();
  }
}

async function loadAndSubscribe() {
  stopStream();
  stoppedByUs = false;
  errorCount = 0;
  logText.value = "";
  loadedBytes = 0;
  status.value = "加载历史日志…";

  try {
    const res = await sessionFetch(`/api/v1/jobs/${encodeURIComponent(props.jobId)}/logs?tail=200000`);
    if (res.ok) {
      const text = await res.text();
      const hdr = res.headers.get("X-MC-Log-Bytes");
      loadedBytes = hdr ? Number(hdr) || text.length : text.length;
      logText.value = text.length > MAX_LOG_CHARS ? text.slice(-MAX_LOG_CHARS) : text;
      scrollToBottom();
      status.value = "已订阅实时日志";
    } else if (res.status === 404) {
      loadedBytes = 0;
      logText.value = "";
      status.value = "等待日志产出…";
    } else {
      const err = await parseApiError(res);
      status.value = apiErrorMessage(err);
      return;
    }
  } catch (e) {
    status.value = apiErrorMessage(e);
    return;
  }

  const tokenRes = await sessionFetch(
    `/api/v1/jobs/${encodeURIComponent(props.jobId)}/logs/stream-token`,
    { method: "POST" },
  );
  if (!tokenRes.ok) {
    const err = await parseApiError(tokenRes);
    status.value = `获取短时流令牌失败：${apiErrorMessage(err)}`;
    return;
  }
  const tokenOut = (await tokenRes.json()) as { access_token?: string };
  const streamToken = (tokenOut.access_token || "").trim();
  if (!streamToken) {
    status.value = "获取短时流令牌失败：响应中缺少 access_token";
    return;
  }
  const url =
    `/api/v1/jobs/${encodeURIComponent(props.jobId)}/logs/stream` +
    `?access_token=${encodeURIComponent(streamToken)}` +
    `&since=${encodeURIComponent(String(loadedBytes))}`;
  es = new EventSource(url);
  es.onmessage = (ev) => {
    errorCount = 0;
    try {
      const data = JSON.parse(ev.data) as { offset?: number; text?: string };
      const offset = Number(data.offset) || 0;
      const chunk = data.text || "";
      if (!chunk) return;
      if (offset <= loadedBytes) return;
      appendLog(chunk);
      loadedBytes = offset;
      if (status.value.includes("等待")) {
        status.value = "已订阅实时日志";
      }
      scrollToBottom();
    } catch {
      /* ignore malformed */
    }
  };
  es.addEventListener("end", () => {
    status.value = "日志流传输完成";
    stopStream();
  });
  es.onerror = () => {
    if (stoppedByUs) return;
    errorCount += 1;
    if (es?.readyState === EventSource.CLOSED || errorCount >= MAX_SSE_ERRORS) {
      status.value =
        errorCount >= MAX_SSE_ERRORS
          ? "实时日志多次连不上，已停止重试"
          : "连接已关闭";
      stopStream();
      return;
    }
    status.value = `实时日志断开（${errorCount}/${MAX_SSE_ERRORS}）`;
  };
}

function onClose() {
  stopStream();
  emit("close");
}

onMounted(() => {
  void loadAndSubscribe();
});

watch(
  () => props.jobId,
  () => {
    void loadAndSubscribe();
  },
);

onUnmounted(() => {
  stopStream();
});
</script>

<template>
  <div class="modal-backdrop" @click.self="onClose">
    <section class="log-viewer-modal animate-slide-up">
      <!-- Modal Header -->
      <div class="log-viewer-header">
        <div class="terminal-dots">
          <span class="dot red-dot"></span>
          <span class="dot yellow-dot"></span>
          <span class="dot green-dot"></span>
          <span class="terminal-title">任务实时输出: {{ jobId.slice(0, 12) }}…</span>
        </div>

        <div class="log-status-and-actions">
          <div class="pulse-indicator-group">
            <span class="pulse-dot" :class="{ running: status.includes('Live') }"></span>
            <span class="status-msg-lbl">{{ status }}</span>
          </div>

          <button 
            type="button" 
            class="small btn-scroller" 
            :class="{ active: autoScroll }" 
            @click="toggleAutoScroll"
            title="锁定或放开：是否跟着新日志自动滚到底"
          >
            <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2.5" fill="none">
              <polyline points="17 11 12 16 7 11" />
              <polyline points="17 4 12 9 7 4" />
            </svg>
            {{ autoScroll ? '滚动锁定开启' : '滚动条已自锁' }}
          </button>

          <button type="button" class="btn-close-modal" @click="onClose" title="关闭控制台">&times;</button>
        </div>
      </div>

      <!-- Modal Body (Terminal Pre-El) -->
      <div class="terminal-screen">
        <pre ref="preEl" class="log-viewer-body">{{ logText || "（控制台暂无任何标准输出产生…）" }}</pre>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Backdrop shadow overlay */
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background-color: var(--overlay);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 2rem;
}

/* Modal box styled as a modern dark editor window */
.log-viewer-modal {
  width: 100%;
  max-width: 960px;
  background-color: var(--log-panel);
  border: 1px solid var(--log-line);
  border-radius: 10px;
  box-shadow: var(--panel-shadow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: min(80vh, 640px);
}

.log-viewer-header {
  height: 44px;
  background-color: var(--log-header);
  border-bottom: 1px solid var(--log-line);
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

/* Red/Yellow/Green Window Dots */
.terminal-dots {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.terminal-dots .dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  display: inline-block;
}

.red-dot { background-color: var(--bad); }
.yellow-dot { background-color: var(--warning); }
.green-dot { background-color: var(--ok); }

.terminal-title {
  margin-left: 0.5rem;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--muted);
}

.log-status-and-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.pulse-indicator-group {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--muted);
}

.pulse-dot.running {
  background-color: var(--ok);
  animation: pulse 1.5s infinite;
}

.status-msg-lbl {
  font-size: 0.75rem;
  color: var(--muted);
  font-weight: 500;
}

.btn-scroller {
  background-color: var(--log-control-bg);
  border-color: var(--log-control-border);
  color: var(--log-btn-fg);
  font-weight: 600;
}

.btn-scroller.active {
  background-color: var(--log-ok-soft-bg);
  border-color: var(--log-ok-soft-border);
  color: var(--log-ok-soft-fg);
}

.btn-scroller:hover {
  background-color: var(--log-control-hover);
}

.btn-close-modal {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 1.5rem;
  cursor: pointer;
  line-height: 1;
  padding: 0.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s;
}

.btn-close-modal:hover {
  color: var(--text);
}

/* Terminal Screen Content Box */
.terminal-screen {
  flex: 1;
  background-color: var(--log-screen);
  padding: 1rem;
  overflow: hidden;
  position: relative;
  display: flex;
}

.log-viewer-body {
  flex: 1;
  margin: 0;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: "JetBrains Mono", ui-monospace, Consolas, Menlo, Monaco, monospace;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--log-fg);
  padding-right: 0.5rem;
  background: transparent;
  border: none;
}

/* Terminal text highlight colors if any logs have stack traces or keywords */
@keyframes pulse {
  0% { transform: scale(0.9); opacity: 0.5; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.9); opacity: 0.5; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.animate-slide-up {
  animation: slideUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
