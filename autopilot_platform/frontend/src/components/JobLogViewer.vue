<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { apiErrorMessage, parseApiError, sessionFetch } from "../api";
import ApModal from "./ApModal.vue";

const props = defineProps<{ jobId: string }>();
const emit = defineEmits<{ close: [] }>();

const MAX_LOG_CHARS = 800_000;
const MAX_SSE_ERRORS = 3;
type LogState = "loading" | "connecting" | "streaming" | "reconnecting" | "ended" | "error";
const logText = ref("");
const state = ref<LogState>("loading");
const error = ref("");
const preEl = ref<HTMLElement | null>(null);
const following = ref(true);
const newLog = ref(false);
const retry = ref(0);
const title = computed(() => `任务日志 ${props.jobId.length > 12 ? props.jobId.slice(0, 12) + "…" : props.jobId}`);
const stateLabel = computed(() => ({
  loading: "正在加载历史日志",
  connecting: "正在连接实时日志",
  streaming: "实时日志已连接",
  reconnecting: "连接已断开，正在重试",
  ended: "日志已结束",
  error: "无法读取实时日志",
})[state.value]);
const emptyLabel = computed(() => {
  if (state.value === "streaming") return "等待任务写入日志。";
  if (state.value === "ended") return "任务已结束，没有日志记录。";
  if (state.value === "error") return "没有可显示的日志。";
  return stateLabel.value;
});

function scrollToBottom() {
  void nextTick(() => {
    const el = preEl.value;
    if (!el || !following.value) return;
    el.scrollTop = el.scrollHeight;
  });
}

function onLogScroll() {
  const el = preEl.value;
  if (el && el.scrollHeight - el.scrollTop - el.clientHeight > 24) following.value = false;
}

function toggleFollow() {
  following.value = !following.value;
  if (following.value) {
    newLog.value = false;
    scrollToBottom();
  }
}

watch([() => props.jobId, retry], async ([jobId], _previous, onCleanup) => {
  const request = new AbortController();
  let source: EventSource | undefined;
  let loadedBytes = 0;
  let errorCount = 0;

  onCleanup(() => {
    request.abort();
    source?.close();
  });
  state.value = "loading";
  error.value = "";
  logText.value = "";
  following.value = true;
  newLog.value = false;
  const path = `/api/v1/jobs/${encodeURIComponent(jobId)}/logs`;
  const signal = request.signal;
  try {
    const res = await sessionFetch(`${path}?tail=200000`, { signal });
    if (res.ok) {
      const text = await res.text();
      if (signal.aborted) return;
      const size = res.headers.get("X-MC-Log-Bytes");
      loadedBytes = size && Number.isFinite(Number(size)) ? Number(size) : new TextEncoder().encode(text).length;
      logText.value = text.slice(-MAX_LOG_CHARS);
      scrollToBottom();
    } else if (res.status !== 404) {
      throw await parseApiError(res);
    }

    if (signal.aborted) return;
    state.value = "connecting";
    const tokenRes = await sessionFetch(`${path}/stream-token`, { method: "POST", signal });
    if (!tokenRes.ok) throw await parseApiError(tokenRes);
    const tokenOut: { access_token?: string } = await tokenRes.json();
    if (signal.aborted) return;
    const token = tokenOut.access_token?.trim();
    if (!token) throw new Error("未获取到实时日志凭据。");
    const params = new URLSearchParams({ access_token: token, since: String(loadedBytes) });
    source = new EventSource(`${path}/stream?${params}`);
    source.onopen = () => {
      if (signal.aborted) return;
      errorCount = 0;
      state.value = "streaming";
    };
    source.onmessage = (event) => {
      if (signal.aborted) return;
      try {
        const data = JSON.parse(event.data) as { offset?: number; text?: string };
        const offset = Number(data.offset);
        if (!data.text || !Number.isFinite(offset) || offset <= loadedBytes) return;
        logText.value = (logText.value + data.text).slice(-MAX_LOG_CHARS);
        loadedBytes = offset;
        errorCount = 0;
        state.value = "streaming";
        if (following.value) scrollToBottom();
        else newLog.value = true;
      } catch {
        // 继续读取后续可解析的日志事件。
      }
    };
    source.addEventListener("end", () => {
      if (signal.aborted) return;
      state.value = "ended";
      source?.close();
    });
    source.onerror = () => {
      if (signal.aborted) return;
      errorCount += 1;
      if (source?.readyState === EventSource.CLOSED || errorCount >= MAX_SSE_ERRORS) {
        state.value = "error";
        error.value = "实时日志连接已关闭，可以重新连接。";
        source?.close();
      } else {
        state.value = "reconnecting";
      }
    };
  } catch (cause) {
    if (signal.aborted) return;
    state.value = "error";
    error.value = apiErrorMessage(cause);
  }
}, { immediate: true });
</script>

<template>
  <ApModal xwide :title="title" @close="emit('close')">
    <div class="log-toolbar">
      <span role="status" :title="jobId">{{ stateLabel }}</span>
      <span v-if="newLog && !following" class="log-new">有新日志</span>
    </div>
    <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
    <pre
      ref="preEl"
      class="log-viewer-body"
      tabindex="0"
      aria-label="日志内容"
      :aria-busy="state === 'loading'"
      @scroll="onLogScroll"
    >{{ logText || emptyLabel }}</pre>
    <template #actions>
      <button v-if="state === 'error'" type="button" class="small" @click="retry++">重新连接</button>
      <button type="button" class="small" :aria-pressed="following" @click="toggleFollow">
        {{ following ? "暂停跟随" : "跟随最新日志" }}
      </button>
      <button type="button" class="small" @click="emit('close')">关闭</button>
    </template>
  </ApModal>
</template>

<style scoped>
.log-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: var(--control-height);
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.log-new {
  color: var(--accent-text);
}

.log-viewer-body {
  box-sizing: border-box;
  height: min(66dvh, 740px);
  min-height: 0;
  margin: 0;
  padding: var(--space-3);
  overflow: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--log-line);
  border-radius: var(--radius-sm);
  background: var(--log-screen);
  color: var(--log-fg);
  font: var(--font-size-meta)/1.55 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
