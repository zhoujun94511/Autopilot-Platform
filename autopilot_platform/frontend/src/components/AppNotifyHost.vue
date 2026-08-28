<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import {
  dismissToast,
  notifyConfirm,
  notifyCopy,
  notifyPrompt,
  notifyToasts,
  pauseToast,
  resumeToast,
  toast,
  type NotifyKind,
} from "../composables/useNotify";
import ApModal from "./ApModal.vue";

const promptValue = ref("");
const promptInput = ref<HTMLInputElement | null>(null);

watch(
  () => notifyPrompt.value,
  async (s) => {
    if (!s) return;
    promptValue.value = s.defaultValue;
    await nextTick();
    promptInput.value?.focus();
    promptInput.value?.select();
  },
);

function isAlertKind(kind: NotifyKind): boolean {
  return kind === "error" || kind === "warn";
}

function onConfirmOk() {
  notifyConfirm.value?.resolve(true);
}
function onConfirmCancel() {
  notifyConfirm.value?.resolve(false);
}
function onPromptOk() {
  notifyPrompt.value?.resolve(promptValue.value);
}
function onPromptCancel() {
  notifyPrompt.value?.resolve(null);
}
async function onCopyClipboard() {
  const v = notifyCopy.value?.value || "";
  try {
    await navigator.clipboard.writeText(v);
    toast("已复制到剪贴板", "success");
  } catch {
    toast("复制失败，请手动选中复制", "error");
  }
}
function onCopyDone() {
  notifyCopy.value?.resolve();
}
</script>

<template>
  <Teleport to="body">
    <div class="ap-toast-stack" aria-label="通知">
      <div
        v-for="t in notifyToasts"
        :key="t.id"
        class="ap-toast"
        :class="t.kind"
        :role="isAlertKind(t.kind) ? 'alert' : 'status'"
        :aria-live="isAlertKind(t.kind) ? 'assertive' : 'polite'"
        @mouseenter="pauseToast(t.id)"
        @mouseleave="resumeToast(t.id)"
      >
        <span class="ap-toast-icon" aria-hidden="true">
          <svg
            v-if="t.kind === 'success'"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
          >
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
            <path
              d="M8 12.5l2.5 2.5L16.5 9"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <svg
            v-else-if="t.kind === 'error'"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
          >
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
            <path
              d="M9 9l6 6M15 9l-6 6"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            />
          </svg>
          <svg
            v-else-if="t.kind === 'warn'"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
          >
            <path
              d="M12 4l9 16H3L12 4z"
              stroke="currentColor"
              stroke-width="2"
              stroke-linejoin="round"
            />
            <path d="M12 10v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            <circle cx="12" cy="17.5" r="0.9" fill="currentColor" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none">
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
            <path d="M12 11v6" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            <circle cx="12" cy="8" r="1" fill="currentColor" />
          </svg>
        </span>
        <p class="ap-toast-text">{{ t.text }}</p>
        <button
          type="button"
          class="ap-toast-close"
          aria-label="关闭通知"
          @click="dismissToast(t.id)"
        >
          ×
        </button>
      </div>
    </div>
  </Teleport>

  <ApModal
    v-if="notifyConfirm"
    stack
    :title="notifyConfirm.title"
    :description="notifyConfirm.text"
    @close="onConfirmCancel"
  >
    <template #actions>
      <button type="button" class="ap-btn ghost" @click="onConfirmCancel">
        {{ notifyConfirm.cancelText }}
      </button>
      <button
        type="button"
        class="ap-btn"
        :class="notifyConfirm.danger ? 'danger' : 'primary'"
        data-autofocus
        @click="onConfirmOk"
      >
        {{ notifyConfirm.okText }}
      </button>
    </template>
  </ApModal>

  <ApModal
    v-else-if="notifyPrompt"
    stack
    :title="notifyPrompt.title"
    :description="notifyPrompt.text"
    @close="onPromptCancel"
  >
    <input
      ref="promptInput"
      v-model="promptValue"
      class="ap-modal-input"
      :type="notifyPrompt.password ? 'password' : 'text'"
      :placeholder="notifyPrompt.placeholder"
      data-autofocus
      @keydown.enter.prevent="onPromptOk"
    />
    <template #actions>
      <button type="button" class="ap-btn ghost" @click="onPromptCancel">
        取消
      </button>
      <button type="button" class="ap-btn primary" @click="onPromptOk">
        确定
      </button>
    </template>
  </ApModal>

  <ApModal
    v-else-if="notifyCopy"
    stack
    :title="notifyCopy.title"
    :description="notifyCopy.text"
    :close-on-backdrop="false"
    @close="onCopyDone"
  >
    <textarea class="ap-modal-textarea" readonly :value="notifyCopy.value" rows="3" />
    <template #actions>
      <button type="button" class="ap-btn ghost" @click="onCopyClipboard">
        复制
      </button>
      <button type="button" class="ap-btn primary" data-autofocus @click="onCopyDone">
        完成
      </button>
    </template>
  </ApModal>
</template>

<style scoped>
.ap-toast-stack {
  position: fixed;
  top: calc(var(--topbar-height, 56px) + 0.75rem);
  right: 1rem;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: min(400px, calc(100vw - 2rem));
  pointer-events: none;
}

.ap-toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  padding: 0.65rem 0.45rem 0.65rem 0.75rem;
  border-radius: var(--radius-lg, 8px);
  font-size: 0.875rem;
  line-height: 1.4;
  color: var(--text);
  background: var(--toast-bg);
  border: 1px solid var(--toast-border);
  border-left-width: 3px;
  box-shadow: var(--elevated-shadow);
  animation: ap-toast-in 0.2s ease;
}

.ap-toast-icon {
  flex-shrink: 0;
  display: inline-flex;
  margin-top: 0.12rem;
}

.ap-toast-text {
  flex: 1;
  margin: 0;
  min-width: 0;
  word-break: break-word;
}

.ap-toast-close {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  margin-top: -0.1rem;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm, 4px);
  background: transparent;
  color: var(--muted);
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
}

.ap-toast-close:hover {
  background: var(--action-hover);
  color: var(--text);
}

.ap-toast-close:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.ap-toast.success {
  border-color: var(--ok-soft-border);
  border-left-color: var(--ok);
  background: var(--toast-ok-bg);
  color: var(--text);
}

.ap-toast.success .ap-toast-icon {
  color: var(--ok-soft-fg);
}

.ap-toast.error {
  border-color: var(--danger-soft-border);
  border-left-color: var(--bad);
  background: var(--toast-bad-bg);
}

.ap-toast.error .ap-toast-icon {
  color: var(--danger-soft-fg);
}

.ap-toast.warn {
  border-color: var(--warning-soft-border);
  border-left-color: var(--warning);
  background: var(--toast-warn-bg);
}

.ap-toast.warn .ap-toast-icon {
  color: var(--warning-soft-fg);
}

.ap-toast.info {
  border-color: var(--info-soft-border);
  border-left-color: var(--accent);
  background: var(--toast-info-bg);
}

.ap-toast.info .ap-toast-icon {
  color: var(--info-soft-fg);
}

@keyframes ap-toast-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ap-toast {
    animation: none;
  }
}
</style>
