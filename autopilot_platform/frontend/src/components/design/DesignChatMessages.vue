<script setup lang="ts">
/**
 * DesignChat 消息列表（AUD-2026-12 Wave 2）。
 */
import { computed, ref } from "vue";
import type { ChatMessage } from "../../api/designChat";
import {
  chatRoleLabel,
  formatChatTime,
  renderChatBody,
} from "../../utils/chatMessageDisplay";
import { CHAT_STARTER_QUESTIONS } from "../../utils/chatStarters";

const props = defineProps<{
  messages: ChatMessage[];
  streamingText: string;
  streamMode: "token" | "buffered" | "";
  generalMode: boolean;
  activeSessionId: string;
  projectReady: boolean;
  starters: string[];
  canPickStarter: boolean;
}>();

const emit = defineEmits<{
  starter: [text: string];
}>();

const rootEl = ref<HTMLElement | null>(null);
defineExpose({ rootEl });

const displayStarters = computed(() =>
  props.starters.length ? props.starters : [...CHAT_STARTER_QUESTIONS],
);
</script>

<template>
  <div ref="rootEl" class="messages">
    <div v-if="generalMode && !messages.length && !streamingText" class="empty-state chat-welcome">
      <p class="empty-title">你好，我是你的AI测试助手</p>
      <p class="empty-desc">
        我可以帮助你解答任何测试相关的问题。
      </p>
      <p class="empty-lead">你可以试着这么问我：</p>
      <ul class="starter-list">
        <li v-for="(q, i) in displayStarters" :key="`st-${i}`">
          <button
            type="button"
            class="starter-btn"
            :disabled="!canPickStarter"
            @click="emit('starter', q)"
          >
            {{ q }}
          </button>
        </li>
      </ul>
    </div>
    <div v-else-if="!generalMode && !activeSessionId" class="empty-state chat-welcome">
      <p class="empty-title">{{ projectReady ? "开始对话" : "请先选择项目" }}</p>
      <p class="empty-desc">
        {{
          projectReady
            ? "点下面的问题，或用提问模板填好再发送；发送时会自动新建会话。"
            : "请先在顶栏选择项目，再新建或选择会话。"
        }}
      </p>
      <template v-if="projectReady">
        <p class="empty-lead">你可以试着这么问：</p>
        <ul class="starter-list">
          <li v-for="(q, i) in displayStarters" :key="`st-p-${i}`">
            <button
              type="button"
              class="starter-btn"
              :disabled="!canPickStarter"
              @click="emit('starter', q)"
            >
              {{ q }}
            </button>
          </li>
        </ul>
      </template>
    </div>
    <template v-else>
      <div v-if="!messages.length && !streamingText" class="empty-state chat-welcome">
        <p class="empty-title">开始对话</p>
        <p class="empty-desc">点下面的问题，或用提问模板快速起步。</p>
        <p class="empty-lead">你可以试着这么问：</p>
        <ul class="starter-list">
          <li v-for="(q, i) in displayStarters" :key="`st-s-${i}`">
            <button
              type="button"
              class="starter-btn"
              :disabled="!canPickStarter"
              @click="emit('starter', q)"
            >
              {{ q }}
            </button>
          </li>
        </ul>
      </div>
      <div
        v-for="m in messages"
        :key="m.id"
        class="msg-bubble"
        :class="m.role === 'assistant' ? 'assistant' : 'user'"
      >
        <div class="bubble-head">
          {{ chatRoleLabel(m.role) }}
          <span v-if="m.model_name" class="model-tag">{{ m.model_name }}</span>
          <span v-if="m.created_at" class="time-tag">{{ formatChatTime(m.created_at) }}</span>
        </div>
        <div class="bubble-body md" v-html="renderChatBody(m.content, m.role)" />
      </div>
      <div v-if="streamingText" class="msg-bubble assistant streaming">
        <div class="bubble-head">
          助手
          <span v-if="streamMode === 'buffered'" class="stream-badge">缓冲分块</span>
          <span v-else-if="streamMode === 'token'" class="stream-badge token">流式</span>
        </div>
        <div class="bubble-body md" v-html="renderChatBody(streamingText, 'assistant')" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.messages {
  flex: 1;
  overflow-y: auto;
  min-height: 8rem;
  padding: 0.35rem 0.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}
.msg-bubble {
  max-width: 92%;
  padding: 0.5rem 0.7rem;
  border-radius: 10px;
  border: 1px solid var(--line);
}
.msg-bubble.user {
  align-self: flex-end;
  background: var(--brand-soft);
}
.msg-bubble.assistant {
  align-self: flex-start;
  background: var(--chip-bg);
}
.msg-bubble.streaming {
  opacity: 0.92;
}
.bubble-head {
  font-size: 0.72rem;
  color: var(--muted);
  margin-bottom: 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.model-tag,
.time-tag {
  opacity: 0.85;
}
.stream-badge {
  font-size: 0.65rem;
  padding: 0.05rem 0.35rem;
  border-radius: 4px;
  background: var(--warning-soft-bg);
  color: var(--warning-soft-fg);
  border: 1px solid var(--warning-soft-border);
}
.stream-badge.token {
  background: var(--ok-soft-bg);
  color: var(--ok-soft-fg);
  border-color: var(--ok-soft-border);
}
.bubble-body {
  font-size: 0.85rem;
  line-height: 1.5;
  word-break: break-word;
}
.bubble-body.md :deep(p) {
  margin: 0 0 0.4rem;
}
.bubble-body.md :deep(p:last-child) {
  margin-bottom: 0;
}
.bubble-body.md :deep(pre.md-code) {
  margin: 0.35rem 0;
  padding: 0.45rem 0.55rem;
  overflow-x: auto;
  border-radius: 6px;
  background: var(--control-bg);
  border: 1px solid var(--line);
  font-size: 0.78rem;
}
.bubble-body.md :deep(code.md-inline) {
  padding: 0.05rem 0.25rem;
  border-radius: 4px;
  background: var(--control-bg);
  font-size: 0.8em;
}
.bubble-body.md :deep(ul),
.bubble-body.md :deep(ol) {
  margin: 0.25rem 0;
  padding-left: 1.2rem;
}
.bubble-body.md :deep(a) {
  color: var(--accent-text);
}
.empty-state.chat-welcome {
  align-items: stretch;
  text-align: left;
  gap: 0.45rem;
  padding: 1rem 1.1rem;
}
.empty-lead {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
  color: var(--muted);
}
.starter-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.starter-btn {
  width: 100%;
  text-align: left;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  border-radius: 8px;
  padding: 0.4rem 0.65rem;
  font-size: 0.8rem;
  line-height: 1.4;
  cursor: pointer;
}
.starter-btn:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--nav-active-bg);
}
.starter-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
