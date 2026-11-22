<script setup lang="ts">
/**
 * Vben Admin v5 风格全局命令搜索（Ctrl+K / Cmd+K）。
 * 复用 router/tabs.ts 路由目录，按当前用户权限裁剪可跳转页面。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { Search, ArrowRight, CornerDownLeft } from "lucide-vue-next";
import { TAB_ROUTES, SECTION_LABELS, type TabRouteDef } from "../../router/tabs";
import { useAuthStore } from "../../stores/auth";
import { useCapabilities } from "../../composables/useCapabilities";

const router = useRouter();
const auth = useAuthStore();
const caps = useCapabilities();
const { canManageUsers } = storeToRefs(auth);

const open = ref(false);
const query = ref("");
const activeIdx = ref(0);
const inputEl = ref<HTMLInputElement | null>(null);

const allowedRoutes = computed<TabRouteDef[]>(() =>
  TAB_ROUTES.filter((r) => {
    if (r.guards.includes("ops") && !caps.canOps) return false;
    if (r.guards.includes("manageUsers") && !canManageUsers.value) return false;
    return true;
  }),
);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return allowedRoutes.value;
  return allowedRoutes.value.filter((r) => {
    const sec = SECTION_LABELS[r.section] || "";
    return (
      r.label.toLowerCase().includes(q) ||
      sec.toLowerCase().includes(q) ||
      r.path.toLowerCase().includes(q) ||
      r.tab.toLowerCase().includes(q)
    );
  });
});

watch(filtered, (list) => {
  if (activeIdx.value >= list.length) activeIdx.value = 0;
});

function openPalette() {
  open.value = true;
  query.value = "";
  activeIdx.value = 0;
  void nextTick(() => inputEl.value?.focus());
}

function closePalette() {
  open.value = false;
}

function jump(item: TabRouteDef) {
  closePalette();
  void router.push(item.path);
}

function onInputKeydown(ev: KeyboardEvent) {
  const list = filtered.value;
  if (!list.length) return;
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    activeIdx.value = (activeIdx.value + 1) % list.length;
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    activeIdx.value = (activeIdx.value - 1 + list.length) % list.length;
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    const target = list[activeIdx.value] ?? list[0];
    if (target) jump(target);
  }
}

function onGlobalKeydown(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
    ev.preventDefault();
    if (open.value) closePalette();
    else openPalette();
    return;
  }
  if (ev.key === "Escape" && open.value) {
    ev.preventDefault();
    closePalette();
  }
}

onMounted(() => document.addEventListener("keydown", onGlobalKeydown));
onUnmounted(() => document.removeEventListener("keydown", onGlobalKeydown));
</script>

<template>
  <button
    type="button"
    class="vben-search-pill"
    title="全局页面导航 (Ctrl+K)"
    aria-label="搜索页面 (Ctrl+K)"
    @click="openPalette"
  >
    <Search :size="14" aria-hidden="true" />
    <span class="vben-search-placeholder">搜索</span>
    <kbd class="vben-kbd">Ctrl K</kbd>
  </button>

  <Teleport to="body">
    <div v-if="open" class="vben-cmd-backdrop" @click.self="closePalette">
      <div class="vben-cmd-dialog" role="dialog" aria-modal="true" aria-label="全局快捷导航">
        <div class="vben-cmd-input-row">
          <Search :size="17" class="vben-cmd-icon" aria-hidden="true" />
          <input
            ref="inputEl"
            v-model="query"
            type="search"
            class="vben-cmd-input"
            placeholder="输入页面名称、分组或路径（如：批跑、设备、用例、审计）…"
            aria-label="搜索导航页面"
            @keydown="onInputKeydown"
          />
          <kbd class="vben-kbd">ESC</kbd>
        </div>

        <ul v-if="filtered.length" class="vben-cmd-list" role="listbox">
          <li
            v-for="(item, idx) in filtered"
            :key="item.tab"
            role="option"
            :aria-selected="idx === activeIdx"
            class="vben-cmd-item"
            :class="{ 'is-active': idx === activeIdx }"
            @mouseenter="activeIdx = idx"
            @click="jump(item)"
          >
            <div class="vben-cmd-item-main">
              <span class="vben-cmd-sec">{{ SECTION_LABELS[item.section] }}</span>
              <span class="vben-cmd-label">{{ item.label }}</span>
            </div>
            <span class="vben-cmd-path">{{ item.path }}</span>
            <ArrowRight :size="14" class="vben-cmd-go" aria-hidden="true" />
          </li>
        </ul>
        <div v-else class="vben-cmd-empty">未找到匹配的页面</div>

        <footer class="vben-cmd-foot">
          <span><CornerDownLeft :size="12" aria-hidden="true" /> 跳转</span>
          <span>↑ ↓ 选择</span>
          <span>ESC 关闭</span>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.vben-search-pill {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--vben-border);
  background: var(--vben-bg-muted);
  color: var(--vben-fg-muted);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background-color 0.15s ease;
}

.vben-search-pill:hover {
  border-color: var(--vben-primary-border);
  color: var(--vben-fg-strong);
  background: var(--vben-bg-hover);
}

.vben-kbd {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 5px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  color: var(--vben-fg-muted);
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
}

.vben-cmd-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10005;
  background: rgba(15, 23, 42, 0.48);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 10vh 16px 16px;
}

.vben-cmd-dialog {
  width: min(560px, 100%);
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: 12px;
  box-shadow: var(--vben-shadow-elevated);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.vben-cmd-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--vben-border-soft);
}

.vben-cmd-icon {
  color: var(--vben-fg-muted);
  flex-shrink: 0;
}

.vben-cmd-input {
  flex: 1;
  min-width: 0;
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  font-size: 15px;
  color: var(--vben-fg-strong);
  outline: 2px solid transparent;
  padding: 2px 0;
}

.vben-cmd-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.vben-cmd-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.12s ease;
}

.vben-cmd-item.is-active {
  background: var(--vben-primary-soft);
  color: var(--vben-primary);
}

.vben-cmd-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.vben-cmd-sec {
  font-size: 12px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--vben-bg-muted);
  color: var(--vben-fg-muted);
}

.vben-cmd-label {
  font-size: 14.5px;
  font-weight: 500;
  color: var(--vben-fg-strong);
}

.vben-cmd-item.is-active .vben-cmd-label {
  color: var(--vben-primary);
}

.vben-cmd-path {
  font-size: 12.5px;
  color: var(--vben-fg-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.vben-cmd-go {
  color: var(--vben-fg-subtle);
  flex-shrink: 0;
}

.vben-cmd-empty {
  padding: 32px 16px;
  text-align: center;
  font-size: 14px;
  color: var(--vben-fg-muted);
}

.vben-cmd-foot {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  border-top: 1px solid var(--vben-border-soft);
  background: var(--vben-bg-muted);
  font-size: 12px;
  color: var(--vben-fg-muted);
}

.vben-cmd-foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 1024px) {
  .vben-search-placeholder,
  .vben-kbd {
    display: none;
  }
  .vben-search-pill {
    padding: 0 8px;
  }
}
</style>
