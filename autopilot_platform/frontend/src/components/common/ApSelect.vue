<script setup lang="ts">
/**
 * 管理台自定义下拉：替代原生 &lt;select&gt;，避免系统弹层与暗色主题打架。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

export type ApSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
  title?: string;
};

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: ApSelectOption[];
    disabled?: boolean;
    required?: boolean;
    id?: string;
    name?: string;
    title?: string;
    ariaLabel?: string;
    ariaDescribedby?: string;
    placeholder?: string;
    size?: "default" | "compact" | "toolbar";
    /** 远控弹窗等高层叠上下文内打开时，下拉须高于 stacked 确认框 (10003) */
    stack?: boolean;
  }>(),
  {
    disabled: false,
    required: false,
    options: () => [],
    size: "default",
    stack: false,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  change: [value: string];
}>();

const open = ref(false);
const activeIndex = ref(0);
const rootRef = ref<HTMLElement | null>(null);
const triggerRef = ref<HTMLButtonElement | null>(null);
const menuRef = ref<HTMLElement | null>(null);
const menuStyle = ref<Record<string, string>>({});
const uid = `ap-sel-${Math.random().toString(36).slice(2, 9)}`;

const selected = computed(
  () => props.options.find((o) => o.value === props.modelValue) || null,
);

const displayLabel = computed(() => {
  if (selected.value) return selected.value.label;
  if (props.placeholder) return props.placeholder;
  const empty = props.options.find((o) => o.value === "" && !o.disabled);
  return empty?.label || "请选择";
});

const isPlaceholder = computed(() => !selected.value);

function enabledIndexes(): number[] {
  return props.options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0);
}

function syncActiveToValue() {
  const idx = props.options.findIndex((o) => o.value === props.modelValue && !o.disabled);
  if (idx >= 0) {
    activeIndex.value = idx;
    return;
  }
  activeIndex.value = enabledIndexes()[0] ?? 0;
}

function placeMenu() {
  const el = triggerRef.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const minW = Math.max(r.width, 8 * 16);
  const maxW = Math.min(28 * 16, vw - 16);
  const width = Math.min(Math.max(minW, r.width), maxW);
  let left = r.left;
  if (left + width > vw - 8) left = Math.max(8, vw - width - 8);
  const below = vh - r.bottom - 8;
  const above = r.top - 8;
  const maxH = 16 * 16;
  const openUp = below < 8 * 16 && above > below;
  if (openUp) {
    menuStyle.value = {
      left: `${left}px`,
      bottom: `${vh - r.top + 4}px`,
      width: `${width}px`,
      maxHeight: `${Math.min(maxH, Math.max(120, above))}px`,
    };
  } else {
    menuStyle.value = {
      left: `${left}px`,
      top: `${r.bottom + 4}px`,
      width: `${width}px`,
      maxHeight: `${Math.min(maxH, Math.max(120, below))}px`,
    };
  }
}

function scrollActiveIntoView() {
  const menu = menuRef.value;
  if (!menu) return;
  const item = menu.querySelector<HTMLElement>(`[data-idx="${activeIndex.value}"]`);
  item?.scrollIntoView({ block: "nearest" });
}

async function setOpen(next: boolean) {
  if (props.disabled) return;
  open.value = next;
  if (!next) return;
  syncActiveToValue();
  placeMenu();
  await nextTick();
  placeMenu();
  scrollActiveIntoView();
}

function toggle() {
  void setOpen(!open.value);
}

function close() {
  open.value = false;
}

function pick(opt: ApSelectOption) {
  if (opt.disabled || props.disabled) return;
  emit("update:modelValue", opt.value);
  emit("change", opt.value);
  close();
  triggerRef.value?.focus();
}

function moveActive(dir: 1 | -1) {
  const enabled = enabledIndexes();
  if (!enabled.length) return;
  const cur = enabled.indexOf(activeIndex.value);
  const next = enabled[(cur < 0 ? 0 : cur + dir + enabled.length) % enabled.length];
  activeIndex.value = next;
  void nextTick(scrollActiveIntoView);
}

function onTriggerKey(ev: KeyboardEvent) {
  if (props.disabled) return;
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    if (!open.value) void setOpen(true);
    else moveActive(ev.key === "ArrowDown" ? 1 : -1);
    return;
  }
  if (ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    if (!open.value) {
      void setOpen(true);
      return;
    }
    const opt = props.options[activeIndex.value];
    if (opt) pick(opt);
    return;
  }
  if (ev.key === "Escape") {
    if (open.value) {
      ev.preventDefault();
      close();
    }
    return;
  }
  if (ev.key === "Home" && open.value) {
    ev.preventDefault();
    activeIndex.value = enabledIndexes()[0] ?? 0;
    void nextTick(scrollActiveIntoView);
  }
  if (ev.key === "End" && open.value) {
    ev.preventDefault();
    const en = enabledIndexes();
    activeIndex.value = en[en.length - 1] ?? 0;
    void nextTick(scrollActiveIntoView);
  }
}

function onDocPointer(ev: PointerEvent) {
  if (!open.value) return;
  const t = ev.target as Node | null;
  if (rootRef.value?.contains(t) || menuRef.value?.contains(t)) return;
  close();
}

function onWinChange() {
  if (open.value) placeMenu();
}

watch(open, (v) => {
  if (v) {
    document.addEventListener("pointerdown", onDocPointer, true);
    window.addEventListener("resize", onWinChange);
    window.addEventListener("scroll", onWinChange, true);
  } else {
    document.removeEventListener("pointerdown", onDocPointer, true);
    window.removeEventListener("resize", onWinChange);
    window.removeEventListener("scroll", onWinChange, true);
  }
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocPointer, true);
  window.removeEventListener("resize", onWinChange);
  window.removeEventListener("scroll", onWinChange, true);
});
</script>

<template>
  <div
    ref="rootRef"
    class="ap-select"
    :class="[`size-${size}`, { open, disabled }]"
  >
    <input
      v-if="required || name"
      class="ap-select-mirror"
      :name="name"
      :value="modelValue"
      :required="required"
      tabindex="-1"
      aria-hidden="true"
      @focus="triggerRef?.focus()"
    />
    <button
      :id="id"
      ref="triggerRef"
      type="button"
      class="ap-select-trigger"
      :disabled="disabled"
      :title="title"
      :aria-label="ariaLabel"
      :aria-describedby="ariaDescribedby"
      :aria-expanded="open"
      :aria-controls="uid"
      :aria-required="required || undefined"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onTriggerKey"
    >
      <span class="ap-select-label" :class="{ placeholder: isPlaceholder }">{{ displayLabel }}</span>
      <svg class="ap-select-chevron" viewBox="0 0 12 12" aria-hidden="true">
        <polyline points="2 4 6 8 10 4" fill="none" stroke="currentColor" stroke-width="1.6" />
      </svg>
    </button>
    <Teleport to="body">
      <ul
        v-if="open"
        :id="uid"
        ref="menuRef"
        class="ap-select-menu"
        :class="{ stacked: stack }"
        role="listbox"
        :aria-labelledby="id"
        :style="menuStyle"
      >
        <li
          v-for="(opt, i) in options"
          :key="`${opt.value || '_empty'}-${i}`"
          :data-idx="i"
          class="ap-select-option"
          role="option"
          :title="opt.title"
          :aria-selected="opt.value === modelValue"
          :aria-disabled="opt.disabled || undefined"
          :class="{
            selected: opt.value === modelValue,
            active: i === activeIndex,
            disabled: opt.disabled,
          }"
          @pointerenter="!opt.disabled && (activeIndex = i)"
          @click="pick(opt)"
        >
          {{ opt.label }}
        </li>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.ap-select {
  position: relative;
  display: inline-flex;
  width: 100%;
  min-width: 0;
  vertical-align: middle;
}
.ap-select.disabled {
  opacity: 0.6;
}
.ap-select-mirror {
  position: absolute;
  opacity: 0;
  width: 0 !important;
  height: 0;
  padding: 0 !important;
  margin: 0;
  border: 0 !important;
  pointer-events: none;
}
.ap-select-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  width: 100%;
  min-width: 0;
  min-height: 34px;
  margin: 0;
  padding: 0.45rem 0.65rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-medium);
  background: var(--input-bg);
  color: var(--text);
  font: inherit;
  font-size: 0.88rem;
  font-weight: 400;
  text-align: left;
  cursor: pointer;
  box-shadow: none;
}
.ap-select-trigger:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--input-bg);
  color: var(--text);
  filter: none;
}
.ap-select-trigger:active {
  filter: none;
}
.ap-select-trigger:disabled {
  opacity: 1;
}
.ap-select-trigger:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}
.ap-select.open .ap-select-trigger {
  border-color: var(--accent);
}
.ap-select-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ap-select-label.placeholder {
  color: var(--muted);
}
.ap-select-chevron {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  opacity: 0.7;
  transition: transform 0.15s ease;
}
.ap-select.open .ap-select-chevron {
  transform: rotate(180deg);
}
.size-compact .ap-select-trigger,
.size-toolbar .ap-select-trigger {
  min-height: 30px;
  padding: 0.2rem 0.5rem;
  font-size: 0.82rem;
}
.size-toolbar .ap-select-trigger {
  min-height: 34px;
  padding: 0 0.65rem;
}
</style>

<style>
.ap-select-menu.stacked {
  z-index: 10004;
}
.ap-select-menu {
  position: fixed;
  z-index: 2400;
  margin: 0;
  padding: 0.25rem;
  list-style: none;
  overflow: auto;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-medium);
  background: var(--surface-elevated);
  color: var(--text);
  box-shadow: var(--elevated-shadow);
}
.ap-select-option {
  padding: 0.4rem 0.55rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  line-height: 1.35;
  cursor: pointer;
  color: var(--text);
}
.ap-select-option.active {
  background: var(--action-hover);
}
.ap-select-option.selected {
  color: var(--accent-text);
  font-weight: 650;
}
.ap-select-option.selected.active {
  background: var(--action-selected);
}
.ap-select-option.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
