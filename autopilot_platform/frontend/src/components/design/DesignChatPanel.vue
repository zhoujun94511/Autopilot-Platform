<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiHttpError } from "../../api";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { confirmDialog, promptDialog } from "../../composables/useNotify";
import {
  clearChatSession,
  cancelExperimentalAction,
  confirmExperimentalAction,
  createChatSession,
  deleteChatSession,
  exportChatSession,
  formatChatError,
  getChatOptions,
  listChatMessages,
  listChatSuggestions,
  renameChatSession,
  sendChatMessage,
  sendEphemeralChat,
  streamChatMessage,
  streamEphemeralChat,
  type ActionPlan,
  type ChatExportFormat,
  type ChatMessage,
  type ChatOptions,
  type ChatSession,
} from "../../api/designChat";
import BrandMark from "../BrandMark.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import DesignChatComposer from "./DesignChatComposer.vue";
import DesignChatMessages from "./DesignChatMessages.vue";
import DesignChatSessionList from "./DesignChatSessionList.vue";
import ApSelect from "../common/ApSelect.vue";
import { useCapabilities } from "../../composables/useCapabilities";
import { useDesignChatFab } from "../../composables/useDesignChatFab";
import { useDesignChatSessions } from "../../composables/useDesignChatSessions";

const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);

const caps = useCapabilities();
const open = ref(false);
const minimized = ref(false);
const messages = ref<ChatMessage[]>([]);
const activeSessionId = ref("");
const inputText = ref("");
const useKnowledge = ref(true);
const actionMode = ref(false);
const pendingAction = ref<{
  execution_id: string;
  plan: ActionPlan;
  message?: string;
} | null>(null);
const deleteConfirmKeyword = ref("");
const sending = ref(false);
const casesJumpVisible = ref(false);
const error = ref("");
const errorRetryable = ref(false);
const streamingText = ref("");
const streamMode = ref<"token" | "buffered" | "">("");
const messagesPanel = ref<InstanceType<typeof DesignChatMessages> | null>(null);
const ctx = ref<{ missing: boolean } | null>(null);
const activeSession = ref<ChatSession | null>(null);

const chatOpts = ref<ChatOptions | null>(null);
const suggestions = ref<string[]>([]);
const exportFormat = ref<ChatExportFormat>("json");
const lastFailedText = ref("");
const composerHint = ref("");

const {
  dragging,
  ignoreClick,
  fabStyle,
  readFabPos,
  onFabPointerDown,
  onFabPointerMove,
  onFabPointerUp,
  onResize,
} = useDesignChatFab();

const keyConfigured = computed(() => Boolean(chatOpts.value?.key_configured));
/** 无项目 = 测试闲聊（不绑项目、不 RAG、不落设计域；人设仍是测试助手） */
const generalMode = computed(() => !filterProjectId.value?.trim());

const {
  sessions,
  sessionsTotal,
  sessionsPage,
  sessionsPageSize,
  sessionsLoading,
  sessionsHasLoaded,
  setSessionsPage,
  setSessionsPageSize,
  loadSessions,
} = useDesignChatSessions({
  generalMode,
  filterProjectId,
  activeSessionId,
  activeSession,
});

watch(activeSessionId, async (id) => {
  activeSession.value = sessions.value.find((s) => s.id === id) || null;
  if (!id) {
    messages.value = [];
    void loadStarterSuggestions();
    return;
  }
  await loadMessages(id);
});

watch(open, (v) => {
  if (v) {
    minimized.value = false;
    void loadOptions();
    void loadStarterSuggestions();
    if (!generalMode.value) void loadSessions();
  }
});

watch(
  () => filterProjectId.value,
  () => {
    if (!open.value) return;
    activeSessionId.value = "";
    messages.value = [];
    streamingText.value = "";
    pendingAction.value = null;
    actionMode.value = false;
    useKnowledge.value = !generalMode.value;
    suggestions.value = [];
    if (generalMode.value) {
      sessions.value = [];
      void loadStarterSuggestions();
    } else {
      void loadSessions(true);
      void loadStarterSuggestions();
    }
  },
);

const projectReady = computed(
  () => Boolean(filterProjectId.value?.trim()) && !ctx.value?.missing,
);
/** 设计模式：已选项目且可写；闲聊模式：登录即可聊 */
const canEdit = computed(() => Boolean(caps.canEditProject));
const canDraft = computed(() => {
  if (sending.value) return false;
  if (generalMode.value) return true;
  return projectReady.value && canEdit.value;
});
const canSend = computed(
  () =>
    canDraft.value &&
    Boolean(inputText.value.trim()) &&
    (keyConfigured.value || (!generalMode.value && actionMode.value)),
);
const dockSubtitle = computed(() =>
  generalMode.value ? "一个可以处理解答任何测试相关问题的AI测试助手" : "设计域对话",
);
const dockTitle = computed(() => "AI测试助手");
function goOpsConfig() {
  shell.openOpsConfig("ai_model");
  minimized.value = true;
}

function toggleOpen() {
  if (ignoreClick.value) return;
  const active = document.activeElement;
  if (active instanceof HTMLElement) active.blur();
  open.value = !open.value;
}

function closeDock() {
  open.value = false;
  minimized.value = false;
}

function minimizeDock() {
  minimized.value = true;
}

function restoreDock() {
  minimized.value = false;
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) closeDock();
}

function setError(err: unknown) {
  const formatted = formatChatError(err);
  error.value = formatted.text;
  errorRetryable.value = formatted.retryable;
}

async function loadStarterSuggestions() {
  try {
    suggestions.value = await listChatSuggestions();
  } catch {
    /* 建议失败不阻断对话 */
  }
}

async function loadOptions() {
  try {
    chatOpts.value = await getChatOptions();
    if (!suggestions.value.length) {
      await loadStarterSuggestions();
    }
  } catch {
    /* 选项失败不阻断对话 */
    if (!suggestions.value.length) {
      await loadStarterSuggestions();
    }
  }
}

async function ensureSession(): Promise<string | null> {
  if (activeSessionId.value) return activeSessionId.value;
  const projectId = filterProjectId.value?.trim();
  if (!projectId || ctx.value?.missing) {
    error.value = "请先在顶部选择项目";
    errorRetryable.value = false;
    return null;
  }
  try {
    const s = await createChatSession({ project_id: projectId, title: "新对话" });
    await loadSessions();
    activeSessionId.value = s.id;
    return s.id;
  } catch (e: unknown) {
    setError(e);
    return null;
  }
}

async function loadMessages(sessionId: string) {
  try {
    messages.value = await listChatMessages(sessionId);
    streamingText.value = "";
    await scrollToBottom();
  } catch (e: any) {
    setError(e);
  }
}

async function scrollToBottom() {
  await nextTick();
  const el = messagesPanel.value?.rootEl ?? null;
  if (el) el.scrollTop = el.scrollHeight;
}

async function onNewSession() {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶部选择项目";
    errorRetryable.value = false;
    return;
  }
  error.value = "";
  try {
    const s = await createChatSession({ project_id: projectId, title: "新对话" });
    await loadSessions();
    activeSessionId.value = s.id;
    minimized.value = false;
    suggestions.value = await listChatSuggestions();
  } catch (e: any) {
    setError(e);
  }
}

async function onRenameSession() {
  if (!activeSessionId.value) return;
  const current = activeSession.value?.title || "";
  const next = await promptDialog("重命名会话", {
    title: "重命名会话",
    defaultValue: current,
  });
  if (next == null) return;
  const title = next.trim();
  if (!title) {
    error.value = "标题不能为空";
    return;
  }
  error.value = "";
  try {
    await renameChatSession(activeSessionId.value, title);
    await loadSessions();
    activeSession.value =
      sessions.value.find((s) => s.id === activeSessionId.value) || null;
  } catch (e: any) {
    setError(e);
  }
}

async function onClearSession() {
  if (!activeSessionId.value) return;
  if (
    !(await confirmDialog("清空当前会话的全部消息？会话本身会保留。", {
      danger: true,
    }))
  ) return;
  error.value = "";
  try {
    await clearChatSession(activeSessionId.value);
    messages.value = [];
    suggestions.value = await listChatSuggestions();
    await loadSessions();
  } catch (e: any) {
    setError(e);
  }
}

async function onDeleteSession() {
  if (!activeSessionId.value) return;
  if (
    !(await confirmDialog("删除当前对话？此操作不可撤销。", {
      danger: true,
    }))
  ) return;
  error.value = "";
  try {
    await deleteChatSession(activeSessionId.value);
    activeSessionId.value = "";
    await loadSessions();
  } catch (e: any) {
    setError(e);
  }
}

async function onExportSession() {
  if (!activeSessionId.value) return;
  error.value = "";
  try {
    await exportChatSession(activeSessionId.value, exportFormat.value);
  } catch (e: any) {
    setError(e);
  }
}

function applyTemplate(content: string) {
  inputText.value = content;
  composerHint.value = "已插入模板，把括号里的内容改成你的情况再发送。";
}

function applySuggestion(text: string) {
  inputText.value = text;
  composerHint.value = generalMode.value
    ? ""
    : activeSessionId.value
      ? ""
      : "已填入建议。发送时将自动新建会话。";
}

function onTemplatePick(id: string) {
  if (!id || !canDraft.value) return;
  const t = chatOpts.value?.templates.find((x) => x.id === id);
  if (t) applyTemplate(t.content);
}

function buildEphemeralHistory(excludeUserText?: string): Array<{ role: string; content: string }> {
  let list = messages.value.filter((m) => m.role === "user" || m.role === "assistant");
  const drop = (excludeUserText || "").trim();
  while (
    drop &&
    list.length &&
    list[list.length - 1].role === "user" &&
    list[list.length - 1].content === drop
  ) {
    list = list.slice(0, -1);
  }
  return list.map((m) => ({ role: m.role, content: m.content })).slice(-20);
}

function onClearEphemeral() {
  messages.value = [];
  streamingText.value = "";
  composerHint.value = "";
  void loadStarterSuggestions();
}

function buildSendBody(text: string, sessionId: string) {
  const body: {
    session_id: string;
    message: string;
    use_knowledge: boolean;
    mode?: string;
    require_confirmation?: boolean;
  } = {
    session_id: sessionId,
    message: text,
    use_knowledge: useKnowledge.value,
  };
  // 模型/温度/Provider 一律走运维配置中心，本面板不覆盖
  if (actionMode.value) {
    body.mode = "action";
    body.require_confirmation = true;
  }
  return body;
}

function applyPendingAction(payload: {
  execution_id?: string;
  plan?: ActionPlan;
  action_plan?: ActionPlan;
  message?: string;
  status?: string;
}) {
  if (payload.status !== "needs_confirmation" || !payload.execution_id) return false;
  const plan = payload.plan || payload.action_plan || {};
  pendingAction.value = {
    execution_id: payload.execution_id,
    plan,
    message: payload.message,
  };
  deleteConfirmKeyword.value = "";
  return true;
}

async function onConfirmAction() {
  if (!pendingAction.value) return;
  const plan = pendingAction.value.plan;
  if (plan.risk_level === "high" && deleteConfirmKeyword.value.trim() !== "删除") {
    error.value = "高风险删除操作请输入「删除」确认";
    return;
  }
  sending.value = true;
  error.value = "";
  try {
    const out = await confirmExperimentalAction({
      execution_id: pendingAction.value.execution_id,
      metadata: { project_id: filterProjectId.value || "" },
    });
    pendingAction.value = null;
    if (!out.success) throw new Error(out.message || "动作执行失败");
    const toolOut = (out.tool_output || {}) as Record<string, unknown>;
    const degraded = Boolean(toolOut.degraded);
    const dedupDropped = Number(toolOut.dedup_dropped || 0);
    let content = `已执行：${plan.tool_name || plan.intent || "action"}\n${JSON.stringify(toolOut, null, 2)}`;
    if (degraded) {
      content =
        "⚠ AI 已降级为启发式生成（degraded=true），请到「意图用例」重点审阅。\n" + content;
    }
    if (dedupDropped > 0) {
      content = `（内容去重丢弃 ${dedupDropped} 条近似草稿）\n` + content;
    }
    messages.value = [
      ...messages.value,
      {
        id: `sys-${Date.now()}`,
        session_id: activeSessionId.value,
        role: "system",
        content,
        created_at: new Date().toISOString(),
      },
    ];
    if (degraded) {
      error.value = "实验动作生成已降级为启发式，请人工审阅产出用例。";
      errorRetryable.value = false;
    }
    const count = Number(toolOut.count || 0);
    if (count > 0 || String(plan.tool_name || "").includes("generate")) {
      casesJumpVisible.value = true;
    }
  } catch (e: any) {
    setError(e);
  } finally {
    sending.value = false;
  }
}

async function onCancelAction() {
  if (!pendingAction.value) return;
  try {
    await cancelExperimentalAction({
      execution_id: pendingAction.value.execution_id,
      reason: "user_cancelled",
    });
  } catch {
    /* ignore */
  }
  pendingAction.value = null;
}

async function onSend(retryText?: string) {
  const text = (retryText ?? inputText.value).trim();
  if (!text || sending.value) return;

  if (generalMode.value) {
    await onSendEphemeral(text, Boolean(retryText));
    return;
  }

  if (!projectReady.value) {
    error.value = "请先在顶部选择项目";
    errorRetryable.value = false;
    return;
  }
  if (!keyConfigured.value && !actionMode.value) {
    error.value = caps.canOps
      ? "AI 尚未开通。请到「运维」填写模型密钥后重试。"
      : "AI 尚未开通。请联系管理员在运维中配置后重试。";
    errorRetryable.value = false;
    return;
  }

  sending.value = true;
  error.value = "";
  errorRetryable.value = false;
  streamingText.value = "";
  streamMode.value = "";
  lastFailedText.value = text;
  pendingAction.value = null;
  composerHint.value = "";

  const sessionId = await ensureSession();
  if (!sessionId) {
    sending.value = false;
    return;
  }

  const userMsg: ChatMessage = {
    id: `tmp-${Date.now()}`,
    session_id: sessionId,
    role: "user",
    content: text,
    created_at: new Date().toISOString(),
  };
  if (!retryText) {
    messages.value = [...messages.value, userMsg];
    inputText.value = "";
  } else if (!messages.value.some((m) => m.content === text && m.role === "user")) {
    messages.value = [...messages.value, userMsg];
  }
  await scrollToBottom();

  const body = buildSendBody(text, sessionId);

  try {
    let streamStarted = false;
    try {
      let gotSuggestions: string[] = [];
      let gotAction = false;
      await streamChatMessage(body, async (ev) => {
        streamStarted = true;
        if (ev.type === "action" || ev.status === "needs_confirmation") {
          gotAction = applyPendingAction(ev);
          return;
        }
        if (ev.stream_mode === "token" || ev.stream_mode === "buffered") {
          streamMode.value = ev.stream_mode;
        }
        if (ev.type === "chunk" || ev.type === "end") {
          streamingText.value = ev.full_response || ev.content || "";
          await scrollToBottom();
        }
        if (ev.type === "end" && Array.isArray(ev.suggestions)) {
          gotSuggestions = ev.suggestions;
        }
        if (ev.type === "error") {
          const err = new Error(ev.message || ev.content || "流式对话失败");
          (err as any).retryable = ev.retryable;
          throw err;
        }
      });
      if (gotAction) {
        lastFailedText.value = "";
        return;
      }
      if (gotSuggestions.length) suggestions.value = gotSuggestions;
      await loadMessages(activeSessionId.value);
      await loadSessions();
      lastFailedText.value = "";
    } catch (streamError) {
      const endpointUnsupported =
        !streamStarted &&
        streamError instanceof ApiHttpError &&
        [404, 405, 501].includes(streamError.status);
      if (!endpointUnsupported) throw streamError;
      const out = await sendChatMessage(body);
      if (applyPendingAction(out)) {
        lastFailedText.value = "";
        return;
      }
      if (out.user_message) {
        messages.value = messages.value.filter((m) => m.id !== userMsg.id);
      }
      await loadMessages(activeSessionId.value);
      await loadSessions();
      if (Array.isArray(out.suggestions) && out.suggestions.length) {
        suggestions.value = out.suggestions;
      }
      if (!out.response && !out.assistant_message) {
        throw new Error("未收到助手回复");
      }
      lastFailedText.value = "";
    }
  } catch (e: any) {
    setError(e);
    await loadMessages(activeSessionId.value);
  } finally {
    streamingText.value = "";
    streamMode.value = "";
    sending.value = false;
    await scrollToBottom();
  }
}

async function onSendEphemeral(text: string, isRetry: boolean) {
  if (!keyConfigured.value) {
    error.value = caps.canOps
      ? "AI 尚未开通。请到「运维」填写模型密钥后重试。"
      : "AI 尚未开通。请联系管理员在运维中配置后重试。";
    errorRetryable.value = false;
    return;
  }

  sending.value = true;
  error.value = "";
  errorRetryable.value = false;
  streamingText.value = "";
  streamMode.value = "";
  lastFailedText.value = text;
  composerHint.value = "";

  const history = buildEphemeralHistory(text);
  const userMsg: ChatMessage = {
    id: `tmp-${Date.now()}`,
    session_id: "ephemeral",
    role: "user",
    content: text,
    created_at: new Date().toISOString(),
  };
  if (!isRetry) {
    messages.value = [...messages.value, userMsg];
    inputText.value = "";
  } else if (!messages.value.some((m) => m.content === text && m.role === "user")) {
    messages.value = [...messages.value, userMsg];
  }
  await scrollToBottom();

  const body = { message: text, history };

  try {
    let streamStarted = false;
    let gotSuggestions: string[] = [];
    let finalText = "";
    try {
      await streamEphemeralChat(body, async (ev) => {
        streamStarted = true;
        if (ev.stream_mode === "token" || ev.stream_mode === "buffered") {
          streamMode.value = ev.stream_mode;
        }
        if (ev.type === "chunk" || ev.type === "end") {
          streamingText.value = ev.full_response || ev.content || "";
          await scrollToBottom();
        }
        if (ev.type === "end") {
          finalText = ev.full_response || ev.content || "";
          if (Array.isArray(ev.suggestions)) gotSuggestions = ev.suggestions;
        }
        if (ev.type === "error") {
          const err = new Error(ev.message || ev.content || "流式对话失败");
          (err as any).retryable = ev.retryable;
          throw err;
        }
      });
    } catch (streamError) {
      const endpointUnsupported =
        !streamStarted &&
        streamError instanceof ApiHttpError &&
        [404, 405, 501].includes(streamError.status);
      if (!endpointUnsupported) throw streamError;
      const out = await sendEphemeralChat(body);
      finalText = out.response || "";
      if (Array.isArray(out.suggestions)) gotSuggestions = out.suggestions;
      if (!finalText) throw new Error("未收到助手回复");
    }
    if (!finalText && streamingText.value) finalText = streamingText.value;
    if (!finalText) throw new Error("未收到助手回复");
    messages.value = [
      ...messages.value,
      {
        id: `ephemeral-a-${Date.now()}`,
        session_id: "ephemeral",
        role: "assistant",
        content: finalText,
        created_at: new Date().toISOString(),
      },
    ];
    if (gotSuggestions.length) suggestions.value = gotSuggestions;
    lastFailedText.value = "";
  } catch (e: any) {
    setError(e);
  } finally {
    streamingText.value = "";
    streamMode.value = "";
    sending.value = false;
    await scrollToBottom();
  }
}

function onRetry() {
  if (!lastFailedText.value || sending.value) return;
  void onSend(lastFailedText.value);
}

onMounted(() => {
  try {
    localStorage.removeItem("ap-mc-chat-fab-pos");
  } catch {
    /* ignore */
  }
  readFabPos();
  document.addEventListener("keydown", onKeydown);
  window.addEventListener("resize", onResize);
});

onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown);
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <!-- 全局悬浮入口：品牌标 + AI 角标，可拖拽 -->
  <button
    v-show="!open"
    type="button"
    class="chat-fab"
    title="AutoPilot AI 助手（可拖拽）"
    aria-label="打开 AI 对话"
    :class="{ dragging }"
    :style="fabStyle"
    @pointerdown="onFabPointerDown"
    @pointermove="onFabPointerMove"
    @pointerup="onFabPointerUp"
    @pointercancel="onFabPointerUp"
    @click="toggleOpen"
  >
    <BrandMark :size="48" />
    <span class="fab-badge" aria-hidden="true">AI</span>
  </button>

  <aside
    v-show="open"
    class="chat-dock"
    :class="{ minimized }"
    role="complementary"
    aria-label="AI 对话"
  >
    <header class="dock-header">
      <div class="dock-brand">
        <BrandMark :size="28" />
        <div class="dock-title">
          <strong>{{ dockTitle }}</strong>
          <span class="dock-sub">{{ dockSubtitle }}</span>
        </div>
      </div>
      <div class="dock-actions">
        <button
          v-if="!minimized"
          type="button"
          class="icon-btn"
          title="最小化"
          aria-label="最小化"
          @click="minimizeDock"
        >
          −
        </button>
        <button
          v-else
          type="button"
          class="icon-btn"
          title="还原"
          aria-label="还原"
          @click="restoreDock"
        >
          □
        </button>
        <button type="button" class="icon-btn" title="关闭" aria-label="关闭" @click="closeDock">
          ×
        </button>
      </div>
    </header>

    <div v-show="!minimized" class="dock-body">
      <div v-if="error" class="msg bad">
        <span>{{ error }}</span>
        <button
          v-if="errorRetryable && lastFailedText"
          type="button"
          class="small retry-btn"
          :disabled="sending"
          @click="onRetry"
        >
          重试
        </button>
      </div>
      <div v-if="casesJumpVisible" class="msg ok info-row">
        <span>已有用例草稿可审阅</span>
        <button
          type="button"
          class="small primary"
          @click="
            shell.activeTab = 'design-cases';
            casesJumpVisible = false;
          "
        >
          打开意图用例
        </button>
      </div>
      <div v-if="chatOpts && !keyConfigured" class="msg warn info-row">
        <span v-if="caps.canOps">尚未开通 AI：请到「运维」填写模型密钥。</span>
        <span v-else>尚未开通 AI：请联系管理员在运维中配置。</span>
        <button
          v-if="caps.canOps"
          type="button"
          class="small primary"
          @click="goOpsConfig"
        >
          打开运维
        </button>
      </div>
      <ProjectContextBanner ref="ctx" :require-project="false" />
      <ProjectReadonlyBanner v-if="!generalMode" />
      <div class="chat-layout" :class="{ 'general-only': generalMode }">
        <DesignChatSessionList
          v-if="!generalMode"
          v-model="activeSessionId"
          :sessions="sessions"
          :sessions-total="sessionsTotal"
          :sessions-page="sessionsPage"
          :sessions-page-size="sessionsPageSize"
          :sessions-loading="sessionsLoading"
          :sessions-has-loaded="sessionsHasLoaded"
          :can-create="!ctx?.missing && canEdit"
          @refresh="loadSessions(true)"
          @create="onNewSession"
          @update:page="setSessionsPage"
          @update:page-size="setSessionsPageSize"
        />

        <section class="surface-card chat-main">
          <div class="card-title-row">
            <h3>
              {{
                generalMode
                  ? "本地临时对话"
                  : activeSession?.title || "选择或新建对话"
              }}
            </h3>
            <div v-if="generalMode && messages.length" class="inline-tools">
              <button type="button" class="small" @click="onClearEphemeral">清空</button>
            </div>
            <div v-else-if="activeSessionId" class="inline-tools">
              <button type="button" class="small" @click="onRenameSession">重命名</button>
              <button type="button" class="small" @click="onClearSession">清空</button>
              <ApSelect
                class="export-fmt"
                size="compact"
                title="导出格式"
                aria-label="导出格式"
                :model-value="exportFormat"
                :options="[
                  { value: 'json', label: 'JSON' },
                  { value: 'txt', label: 'TXT' },
                  { value: 'csv', label: 'CSV' },
                  { value: 'xlsx', label: 'Excel' },
                ]"
                @update:model-value="exportFormat = $event as ChatExportFormat"
              />
              <button type="button" class="small" @click="onExportSession">导出</button>
              <button type="button" class="small danger" @click="onDeleteSession">删除</button>
            </div>
          </div>

          <div v-if="!generalMode" class="model-bar">
            <label class="check-line compact" title="把当前项目知识库一起交给助手">
              <input v-model="useKnowledge" type="checkbox" :disabled="!canDraft" />
              知识库
            </label>
            <label
              class="check-line compact"
              title="开启后可以让助手生成或删除用例，执行前会再确认"
            >
              <input v-model="actionMode" type="checkbox" :disabled="!canDraft" />
              实验动作
            </label>
          </div>
          <p v-if="!generalMode && actionMode" class="composer-hint">
            已开启：识别到生成/删除等操作时，会先请你确认再执行。
          </p>

          <div v-if="pendingAction" class="action-panel surface-card">
            <div class="action-title">待确认动作</div>
            <p class="meta-line">{{ pendingAction.message || pendingAction.plan.reason }}</p>
            <p class="meta-line">
              意图 <code>{{ pendingAction.plan.intent }}</code>
              · 工具 <code>{{ pendingAction.plan.tool_name }}</code>
              · 风险 <span class="pill" :class="{ bad: pendingAction.plan.risk_level === 'high' }">
                {{ pendingAction.plan.risk_level || "—" }}
              </span>
            </p>
            <pre class="action-args">{{ JSON.stringify(pendingAction.plan.args || {}, null, 2) }}</pre>
            <label
              v-if="pendingAction.plan.risk_level === 'high'"
              class="field-label"
            >
              高风险确认（输入「删除」）
              <input v-model="deleteConfirmKeyword" type="text" placeholder="删除" />
            </label>
            <div class="row-actions">
              <button type="button" class="primary" :disabled="sending" @click="onConfirmAction">
                确认执行
              </button>
              <button type="button" :disabled="sending" @click="onCancelAction">取消</button>
            </div>
          </div>

          <DesignChatMessages
            ref="messagesPanel"
            :messages="messages"
            :streaming-text="streamingText"
            :stream-mode="streamMode"
            :general-mode="generalMode"
            :active-session-id="activeSessionId"
            :project-ready="projectReady"
            :starters="suggestions"
            :can-pick-starter="canDraft"
            @starter="applySuggestion"
          />

          <DesignChatComposer
            v-model="inputText"
            :suggestions="suggestions"
            :templates="chatOpts?.templates ?? []"
            :show-templates="Boolean((chatOpts?.templates ?? []).length) && canDraft"
            :show-followups="Boolean(messages.length || streamingText)"
            :can-draft="canDraft"
            :can-send="canSend"
            :sending="sending"
            :general-mode="generalMode"
            :project-ready="projectReady"
            :key-configured="keyConfigured"
            :action-mode="actionMode"
            :can-edit="canEdit"
            :composer-hint="composerHint"
            @send="onSend()"
            @suggestion="applySuggestion"
            @template="onTemplatePick"
          />
        </section>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.chat-fab {
  position: fixed;
  z-index: 1200;
  width: 56px;
  height: 56px;
  padding: 0;
  border: none;
  border-radius: 14px;
  background: transparent;
  color: var(--on-accent);
  cursor: grab;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
  user-select: none;
  /* 与 BrandMark 圆角徽章一致，阴影带品牌色 */
  filter: drop-shadow(0 6px 14px rgba(21, 101, 192, 0.42));
  transition: transform 0.18s ease, filter 0.18s ease;
}
.chat-fab:hover {
  transform: translateY(-2px);
  filter: drop-shadow(0 10px 22px rgba(21, 101, 192, 0.55));
}
.chat-fab:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.chat-fab.dragging,
.chat-fab:active {
  cursor: grabbing;
  transform: scale(0.97);
  filter: drop-shadow(0 4px 10px rgba(21, 101, 192, 0.4));
}
.chat-fab :deep(.ap-mark) {
  display: block;
  width: 48px;
  height: 48px;
  pointer-events: none;
}
.fab-badge {
  position: absolute;
  right: -2px;
  bottom: -2px;
  min-width: 1.35rem;
  height: 1.15rem;
  padding: 0 0.28rem;
  border-radius: 6px;
  border: 1.5px solid var(--surface-canvas);
  background: var(--brand-pressed);
  color: #fff;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.15rem;
  text-align: center;
  pointer-events: none;
}

.chat-dock {
  position: fixed;
  z-index: 1190;
  top: 56px;
  right: 12px;
  bottom: 12px;
  width: min(960px, calc(100vw - 24px));
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--panel-shadow);
  overflow: hidden;
  pointer-events: auto;
}
.chat-dock.minimized {
  top: auto;
  bottom: 16px;
  right: 16px;
  width: min(320px, calc(100vw - 32px));
  height: auto;
}

.dock-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--line);
  background: var(--surface-soft);
  flex-shrink: 0;
}
.dock-brand {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.dock-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.dock-title strong {
  font-size: 0.9rem;
  color: var(--text);
}
.dock-sub {
  font-size: 0.72rem;
  color: var(--muted);
}
.dock-actions {
  display: flex;
  gap: 0.25rem;
}
.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--control-bg);
  color: var(--text);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.icon-btn:hover {
  background: var(--control-bg-hover);
}

.dock-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.msg.bad,
.msg.warn {
  margin: 0;
  padding: 0.55rem 0.75rem;
  border-radius: 8px;
  font-size: 0.85rem;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.msg.bad {
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
}
.msg.warn {
  background: var(--warning-soft-bg);
  border: 1px solid var(--warning-soft-border);
  color: var(--warning-soft-fg);
}
.msg.ok {
  margin: 0;
  padding: 0.55rem 0.75rem;
  border-radius: 8px;
  font-size: 0.85rem;
  flex-shrink: 0;
  background: var(--ok-soft-bg, var(--brand-soft));
  border: 1px solid var(--ok-soft-border, var(--line));
  color: var(--ok-soft-fg, var(--text));
}
.info-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.retry-btn {
  flex-shrink: 0;
}

.chat-layout {
  display: grid;
  grid-template-columns: minmax(160px, 230px) 1fr;
  gap: 0.75rem;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.chat-layout.general-only {
  grid-template-columns: 1fr;
}
@media (max-width: 720px) {
  .chat-layout {
    grid-template-columns: 1fr;
  }
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.model-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 0.85rem;
  align-items: center;
  margin-bottom: 0.45rem;
  font-size: 0.78rem;
  color: var(--muted);
}
.model-bar label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}
.export-fmt {
  max-width: 12rem;
}
.check-line.compact {
  font-size: 0.78rem;
}
.composer-hint {
  margin: 0 0 0.35rem;
  font-size: 0.74rem;
  color: var(--muted);
  line-height: 1.35;
}
.composer-hint.warn {
  color: var(--warning-soft-fg);
}
.action-panel {
  margin: 0.5rem 0;
  padding: 0.75rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-soft);
}
.action-title {
  font-weight: 600;
  margin-bottom: 0.35rem;
}
.meta-line {
  display: flex;
  justify-content: space-between;
  gap: 0.35rem;
  font-size: 0.68rem;
  color: var(--muted);
  margin-top: 0.2rem;
}
.action-args {
  margin: 0.45rem 0;
  padding: 0.5rem;
  max-height: 8rem;
  overflow: auto;
  font-size: 0.72rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.inline-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}
.check-line {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.85rem;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}
.check-line input {
  width: auto;
  margin: 0;
}
</style>
