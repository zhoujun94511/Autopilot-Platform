<script setup lang="ts">
/**
 * DesignChat 建议 / 模板 / 输入框（AUD-2026-12 Wave 2）。
 */
import { computed, ref } from "vue";
import type { ChatOptions } from "../../api/designChat";
import ApSelect from "../common/ApSelect.vue";

const inputText = defineModel<string>({ required: true });

const props = defineProps<{
  suggestions: string[];
  templates: ChatOptions["templates"];
  showTemplates: boolean;
  showFollowups: boolean;
  canDraft: boolean;
  canSend: boolean;
  sending: boolean;
  generalMode: boolean;
  projectReady: boolean;
  keyConfigured: boolean;
  actionMode: boolean;
  canEdit: boolean;
  composerHint: string;
}>();

const emit = defineEmits<{
  send: [];
  suggestion: [text: string];
  template: [templateId: string];
}>();

const templatePick = ref("");
const templateOptions = computed(() => [
  { value: "", label: "插入模板…" },
  ...props.templates.map((t) => ({ value: t.id, label: t.name })),
]);

function onTemplatePick(id: string) {
  if (id) emit("template", id);
  templatePick.value = "";
}
</script>

<template>
  <div class="composer-block">
    <div v-if="suggestions.length && showFollowups" class="suggestions">
      <button
        v-for="(s, i) in suggestions"
        :key="`sg-${i}`"
        type="button"
        class="chip"
        :disabled="!canDraft"
        :title="generalMode || projectReady ? '填入输入框' : '请先选择项目'"
        @click="emit('suggestion', s)"
      >
        {{ s }}
      </button>
    </div>

    <div v-if="showTemplates && templates.length" class="templates">
      <span class="tpl-label">提问模板</span>
      <ApSelect
        size="compact"
        :disabled="!canDraft"
        :title="generalMode || projectReady ? '插入到输入框，可改括号里的内容' : '请先选择项目'"
        :model-value="templatePick"
        :options="templateOptions"
        aria-label="提问模板"
        @update:model-value="onTemplatePick"
      />
    </div>

    <div class="composer">
      <p v-if="composerHint" class="composer-hint">{{ composerHint }}</p>
      <p
        v-else-if="!keyConfigured && (generalMode || (!actionMode && projectReady))"
        class="composer-hint warn"
      >
        AI 尚未开通，无法发送普通对话；{{
          generalMode ? "请联系管理员配置模型。" : "可开启「实验动作」或请联系管理员配置模型。"
        }}
      </p>
      <p v-else-if="!generalMode && projectReady && !canEdit" class="composer-hint warn">
        当前为项目只读成员，无法发送对话或执行写操作。
      </p>
      <div class="composer-row">
        <textarea
          v-model="inputText"
          rows="3"
          :placeholder="
            generalMode
              ? '请输入你的问题…（Enter 发送，Shift+Enter 换行）'
              : projectReady
                ? '请输入你的问题…（Enter 发送，Shift+Enter 换行；无会话时自动新建）'
                : '请先选择项目后再输入…'
          "
          :disabled="!canDraft"
          @keydown.enter.exact.prevent="emit('send')"
          @keydown.ctrl.enter.prevent="emit('send')"
          @keydown.meta.enter.prevent="emit('send')"
        />
        <button
          type="button"
          class="primary send-btn"
          :disabled="!canSend"
          @click="emit('send')"
        >
          {{ sending ? "发送中…" : "发送" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer-block {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.35rem;
}
.chip {
  border: 1px solid var(--line);
  background: var(--chip-bg);
  color: var(--text);
  border-radius: 999px;
  padding: 0.2rem 0.55rem;
  font-size: 0.72rem;
  cursor: pointer;
}
.chip:hover:not(:disabled) {
  background: var(--nav-active-bg);
}
.chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.templates {
  margin-top: 0.45rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.tpl-label {
  font-size: 0.74rem;
  color: var(--muted);
}
.templates .ap-select {
  max-width: 14rem;
}
.composer {
  margin-top: 0.5rem;
  border-top: 1px solid var(--line);
  padding-top: 0.65rem;
  flex-shrink: 0;
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
.composer-row {
  display: flex;
  gap: 0.55rem;
  align-items: flex-end;
}
.composer-row textarea {
  flex: 1;
  resize: vertical;
  min-height: 3.5rem;
  max-height: 8rem;
}
.send-btn {
  flex-shrink: 0;
}
</style>
