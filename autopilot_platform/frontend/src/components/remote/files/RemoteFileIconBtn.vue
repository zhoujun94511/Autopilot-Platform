<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string;
    label?: string;
    variant?: "default" | "danger";
    disabled?: boolean;
  }>(),
  { variant: "default", disabled: false },
);

defineEmits<{ click: [] }>();
</script>

<template>
  <button
    type="button"
    class="remote-file-icon-btn"
    :class="variant"
    :title="title"
    :aria-label="label || title"
    :disabled="disabled"
    @click.stop="$emit('click')"
  >
    <slot />
    <span v-if="label" class="sr-only">{{ label }}</span>
  </button>
</template>

<style scoped>
.remote-file-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-md, 6px);
  color: var(--text-secondary);
  background: var(--btn-bg, var(--surface-primary));
  cursor: pointer;
  transition:
    color 0.12s ease,
    background-color 0.12s ease,
    border-color 0.12s ease;
}

.remote-file-icon-btn:hover:not(:disabled) {
  color: var(--accent-text);
  border-color: var(--line);
  background: var(--btn-bg-hover, var(--action-hover));
}

.remote-file-icon-btn.danger {
  color: var(--danger-soft-fg);
  border-color: var(--danger-soft-border);
  background: var(--danger-soft-bg);
}

.remote-file-icon-btn.danger:hover:not(:disabled) {
  color: var(--bad);
  border-color: var(--bad);
  background: var(--danger-soft-bg);
}

.remote-file-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.remote-file-icon-btn :deep(svg) {
  width: 15px;
  height: 15px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
