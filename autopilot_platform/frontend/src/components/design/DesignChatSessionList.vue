<script setup lang="ts">
/**
 * DesignChat 会话侧栏（AUD-2026-12 Wave 3）。
 */
import type { ChatSession } from "../../api/designChat";
import { formatChatTime } from "../../utils/chatMessageDisplay";
import DataPager from "../common/DataPager.vue";

const activeSessionId = defineModel<string>({ required: true });

defineProps<{
  sessions: ChatSession[];
  sessionsTotal: number;
  sessionsPage: number;
  sessionsPageSize: number;
  sessionsLoading: boolean;
  sessionsHasLoaded?: boolean;
  canCreate: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
  create: [];
  "update:page": [page: number];
  "update:pageSize": [pageSize: number];
}>();
</script>

<template>
  <aside class="surface-card session-list">
    <div class="card-title-row">
      <h3>会话</h3>
      <span class="count-chip">{{ sessionsLoading ? "…" : sessionsTotal }}</span>
    </div>
    <div class="session-tools">
      <button
        type="button"
        class="small"
        :disabled="sessionsLoading"
        @click="emit('refresh')"
      >
        刷新
      </button>
      <button
        type="button"
        class="small primary"
        :disabled="!canCreate"
        @click="emit('create')"
      >
        新建
      </button>
    </div>
    <div v-if="!sessions.length && sessionsHasLoaded" class="empty-state compact">
      <p class="empty-desc">暂无对话，点击「新建」开始。</p>
    </div>
    <ul v-else-if="sessions.length" class="session-items">
      <li v-for="s in sessions" :key="s.id">
        <button
          type="button"
          class="session-item"
          :class="{ active: s.id === activeSessionId }"
          :aria-current="s.id === activeSessionId ? 'true' : undefined"
          @click="activeSessionId = s.id"
        >
          <span class="session-title">{{ s.title || "未命名对话" }}</span>
          <span class="session-preview">{{ s.preview || "暂无消息" }}</span>
          <span class="meta-line">
            <span>{{ formatChatTime(s.updated_at) }}</span>
            <span class="msg-count">{{ s.message_count ?? 0 }} 条</span>
          </span>
        </button>
      </li>
    </ul>
    <DataPager
      v-if="sessionsTotal > 0"
      :total="sessionsTotal"
      :page="sessionsPage"
      :page-size="sessionsPageSize"
      :loading="sessionsLoading"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:pageSize', $event)"
    />
  </aside>
</template>

<style scoped>
.session-list {
  overflow: auto;
  min-height: 0;
}
.session-tools {
  display: flex;
  gap: 0.35rem;
  margin-bottom: 0.5rem;
}
.session-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.session-item {
  display: grid;
  justify-content: stretch;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}
.session-item:hover:not(:disabled) {
  background: var(--chip-bg);
}
.session-item.active {
  background: var(--nav-active-bg);
  border-color: var(--accent);
}
.session-title {
  font-size: var(--font-size-body);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-preview {
  font-size: var(--font-size-meta);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 0.15rem;
}
.meta-line {
  display: flex;
  justify-content: space-between;
  gap: 0.35rem;
  font-size: var(--font-size-meta);
  color: var(--muted);
  margin-top: 0.2rem;
}
.msg-count {
  flex-shrink: 0;
}
.empty-state.compact {
  padding: 0.5rem 0;
}
@media (max-width: 720px) {
  .session-list {
    max-height: 8rem;
  }
}
</style>
