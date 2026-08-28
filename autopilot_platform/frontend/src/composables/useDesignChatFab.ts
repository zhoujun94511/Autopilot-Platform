/**
 * DesignChat 浮动按钮拖拽 / 位置缓存（AUD-2026-12 Wave 1）。
 */
import { computed, ref } from "vue";
import {
  CHAT_FAB_EDGE,
  CHAT_FAB_POS_KEY,
  clampChatFab,
  defaultChatFabPos,
  parseChatFabPos,
} from "../utils/chatFabPosition";

export function useDesignChatFab() {
  const fabLeft = ref<number | null>(null);
  const fabTop = ref<number | null>(null);
  const dragging = ref(false);
  const ignoreClick = ref(false);
  let dragPtr: {
    pointerId: number;
    startX: number;
    startY: number;
    startLeft: number;
    startTop: number;
    moved: boolean;
  } | null = null;

  /** 未拖动：CSS 锚定右下角；拖动后改用 left/top 像素 */
  const fabStyle = computed(() => {
    if (fabLeft.value == null || fabTop.value == null) {
      return {
        right: `${CHAT_FAB_EDGE}px`,
        bottom: `${CHAT_FAB_EDGE}px`,
        left: "auto",
        top: "auto",
      };
    }
    return {
      left: `${fabLeft.value}px`,
      top: `${fabTop.value}px`,
      right: "auto",
      bottom: "auto",
    };
  });

  function readFabPos() {
    try {
      const c = parseChatFabPos(localStorage.getItem(CHAT_FAB_POS_KEY));
      if (!c) return;
      fabLeft.value = c.left;
      fabTop.value = c.top;
    } catch {
      /* ignore */
    }
  }

  function saveFabPos() {
    if (fabLeft.value == null || fabTop.value == null) return;
    try {
      localStorage.setItem(
        CHAT_FAB_POS_KEY,
        JSON.stringify({ left: fabLeft.value, top: fabTop.value }),
      );
    } catch {
      /* ignore */
    }
  }

  function materializeFabPos(el?: HTMLElement | null) {
    if (fabLeft.value != null && fabTop.value != null) {
      return { left: fabLeft.value, top: fabTop.value };
    }
    if (el) {
      const r = el.getBoundingClientRect();
      return clampChatFab(r.left, r.top);
    }
    return defaultChatFabPos();
  }

  function onFabPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const cur = materializeFabPos(e.currentTarget as HTMLElement);
    dragPtr = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startLeft: cur.left,
      startTop: cur.top,
      moved: false,
    };
    dragging.value = true;
    (e.currentTarget as HTMLElement)?.setPointerCapture?.(e.pointerId);
  }

  function onFabPointerMove(e: PointerEvent) {
    if (!dragPtr || dragPtr.pointerId !== e.pointerId) return;
    const dx = e.clientX - dragPtr.startX;
    const dy = e.clientY - dragPtr.startY;
    if (Math.abs(dx) + Math.abs(dy) > 4) {
      dragPtr.moved = true;
      if (fabLeft.value == null || fabTop.value == null) {
        fabLeft.value = dragPtr.startLeft;
        fabTop.value = dragPtr.startTop;
      }
    }
    if (!dragPtr.moved) return;
    const c = clampChatFab(dragPtr.startLeft + dx, dragPtr.startTop + dy);
    fabLeft.value = c.left;
    fabTop.value = c.top;
  }

  function onFabPointerUp(e: PointerEvent) {
    if (!dragPtr || dragPtr.pointerId !== e.pointerId) return;
    const moved = dragPtr.moved;
    dragPtr = null;
    dragging.value = false;
    if (moved) {
      saveFabPos();
      ignoreClick.value = true;
      window.setTimeout(() => {
        ignoreClick.value = false;
      }, 0);
    }
  }

  function onResize() {
    if (fabLeft.value != null && fabTop.value != null) {
      const c = clampChatFab(fabLeft.value, fabTop.value);
      fabLeft.value = c.left;
      fabTop.value = c.top;
    }
  }

  return {
    fabLeft,
    fabTop,
    dragging,
    ignoreClick,
    fabStyle,
    readFabPos,
    onFabPointerDown,
    onFabPointerMove,
    onFabPointerUp,
    onResize,
  };
}
