<script setup lang="ts">
/**
 * 弹窗基座：所有 modal 共用的遮罩 / 焦点 / 键盘语义。
 *
 * 提供 Esc 关闭、点遮罩关闭、焦点陷阱、关闭后归还触发元素焦点、aria 关联。
 * 视觉样式在 styles.css 全局（`.ap-modal*`），因为具名插槽内容属父组件作用域。
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    /** 表单类弹窗用 wide（520px） */
    wide?: boolean;
    /** 远控/双栏面板用 xwide（~1120px） */
    xwide?: boolean;
    /** 叠在其它 ApModal 之上（如远控内 confirm/prompt） */
    stack?: boolean;
    closeOnBackdrop?: boolean;
    closeOnEsc?: boolean;
  }>(),
  { closeOnBackdrop: true, closeOnEsc: true, wide: false, xwide: false, stack: false },
);

const emit = defineEmits<{ (e: "close"): void }>();

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

let idSeq = 0;
const uid = `ap-modal-${++idSeq}-${Math.random().toString(36).slice(2, 7)}`;
const titleId = `${uid}-title`;
const descId = `${uid}-desc`;

const card = ref<HTMLElement | null>(null);
let restoreTo: HTMLElement | null = null;

function focusables(): HTMLElement[] {
  const root = card.value;
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement,
  );
}

function onBackdrop() {
  if (props.closeOnBackdrop) emit("close");
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === "Escape") {
    if (!props.closeOnEsc) return;
    ev.preventDefault();
    ev.stopPropagation();
    emit("close");
    return;
  }
  if (ev.key !== "Tab") return;
  const items = focusables();
  if (!items.length) {
    ev.preventDefault();
    card.value?.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement as HTMLElement | null;
  const inside = Boolean(active && card.value?.contains(active));
  if (ev.shiftKey && (!inside || active === first)) {
    ev.preventDefault();
    last.focus();
  } else if (!ev.shiftKey && (!inside || active === last)) {
    ev.preventDefault();
    first.focus();
  }
}

onMounted(async () => {
  const active = document.activeElement;
  restoreTo = active instanceof HTMLElement ? active : null;
  await nextTick();
  const auto = card.value?.querySelector<HTMLElement>("[data-autofocus]");
  (auto || focusables()[0] || card.value)?.focus();
});

onBeforeUnmount(() => {
  // 归还焦点，避免关闭后焦点落到 body 导致键盘用户丢失位置
  if (restoreTo && document.body.contains(restoreTo)) restoreTo.focus();
});
</script>

<template>
  <Teleport to="body">
    <div
      class="ap-modal-backdrop"
      :class="{ stacked: stack }"
      @click.self="onBackdrop"
      @keydown="onKeydown"
    >
      <div
        ref="card"
        class="ap-modal"
        :class="{ wide, xwide }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="description ? descId : undefined"
        tabindex="-1"
      >
        <h3 :id="titleId" class="ap-modal-title">{{ title }}</h3>
        <p v-if="description" :id="descId" class="ap-modal-body">{{ description }}</p>
        <slot />
        <div class="ap-modal-actions">
          <slot name="actions" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
