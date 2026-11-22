<script setup lang="ts">
/**
 * Vben Admin v5 风格多页签栏（38px）。
 * 与现有 router/tabs.ts 与 KeepAlive 无缝协同；包含权限裁剪、登出重置与外点/Esc 关闭。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { RotateCw, X, Pin, ChevronDown } from "lucide-vue-next";
import { useAuthStore } from "../../stores/auth";
import { useShellStore } from "../../stores/shellStore";
import { useCapabilities } from "../../composables/useCapabilities";
import { labelForTab, normalizeTabId, pathForTab } from "../../router/tabs";
import type { McTabId } from "../../composables/mcRefreshScopes";

const props = defineProps<{
  refreshing?: boolean;
}>();

const emit = defineEmits<{
  (e: "refresh"): void;
}>();

const router = useRouter();
const auth = useAuthStore();
const shell = useShellStore();
const caps = useCapabilities();
const { loggedIn, canManageUsers } = storeToRefs(auth);
const { activeTab } = storeToRefs(shell);

const PINNED_TAB: McTabId = "dashboard";
const visitedTabs = ref<McTabId[]>([PINNED_TAB]);
const menuOpen = ref(false);

function isTabAllowed(id: McTabId): boolean {
  if (id === "ops") return Boolean(caps.canOps);
  if (id === "audit" || id === "users") return Boolean(canManageUsers.value);
  return true;
}

function ensureTab(raw: string) {
  const id = normalizeTabId(raw);
  if (!isTabAllowed(id)) return;
  if (!visitedTabs.value.includes(id)) {
    visitedTabs.value = [...visitedTabs.value, id];
  }
}

watch(
  () => activeTab.value,
  (tab) => {
    ensureTab(tab);
  },
  { immediate: true },
);

watch(
  () => [loggedIn.value, caps.canOps, canManageUsers.value] as const,
  ([isLogged]) => {
    if (!isLogged) {
      visitedTabs.value = [PINNED_TAB];
      menuOpen.value = false;
      return;
    }
    visitedTabs.value = visitedTabs.value.filter((id) => id === PINNED_TAB || isTabAllowed(id));
  },
);

function onGlobalClick(ev: MouseEvent) {
  if (!menuOpen.value) return;
  const target = ev.target as HTMLElement | null;
  if (!target?.closest(".vben-tab-menu-wrap")) {
    menuOpen.value = false;
  }
}

function onGlobalKeydown(ev: KeyboardEvent) {
  if (ev.key === "Escape" && menuOpen.value) {
    menuOpen.value = false;
  }
}

onMounted(() => {
  document.addEventListener("click", onGlobalClick);
  document.addEventListener("keydown", onGlobalKeydown);
});

onUnmounted(() => {
  document.removeEventListener("click", onGlobalClick);
  document.removeEventListener("keydown", onGlobalKeydown);
});

const tabs = computed(() =>
  visitedTabs.value.map((id) => ({
    id,
    label: labelForTab(id) || id,
    path: pathForTab(id),
    pinned: id === PINNED_TAB,
    active: activeTab.value === id,
  })),
);

function selectTab(id: McTabId) {
  menuOpen.value = false;
  if (activeTab.value === id) return;
  void router.push(pathForTab(id));
}

function closeTab(id: McTabId) {
  if (id === PINNED_TAB) return;
  const idx = visitedTabs.value.indexOf(id);
  if (idx === -1) return;
  const next = visitedTabs.value.filter((t) => t !== id);
  visitedTabs.value = next.length ? next : [PINNED_TAB];
  if (activeTab.value === id) {
    const fallback = visitedTabs.value[Math.max(0, idx - 1)] ?? PINNED_TAB;
    void router.push(pathForTab(fallback));
  }
}

function closeOtherTabs() {
  menuOpen.value = false;
  const current = normalizeTabId(activeTab.value);
  visitedTabs.value = current === PINNED_TAB ? [PINNED_TAB] : [PINNED_TAB, current];
}

function closeAllTabs() {
  menuOpen.value = false;
  visitedTabs.value = [PINNED_TAB];
  if (activeTab.value !== PINNED_TAB) {
    void router.push(pathForTab(PINNED_TAB));
  }
}
</script>

<template>
  <div class="vben-tabbar" role="tablist" aria-label="已打开页面">
    <div class="vben-tabbar-scroll">
      <div
        v-for="item in tabs"
        :key="item.id"
        role="tab"
        tabindex="0"
        :aria-selected="item.active"
        class="vben-tab-item"
        :class="{ 'is-active': item.active }"
        @click="selectTab(item.id)"
        @keydown.enter.prevent="selectTab(item.id)"
        @keydown.space.prevent="selectTab(item.id)"
      >
        <span class="vben-tab-label">{{ item.label }}</span>
        <Pin v-if="item.pinned" :size="11" class="vben-tab-pin" aria-hidden="true" />
        <button
          v-else
          type="button"
          class="vben-tab-close"
          :aria-label="`关闭 ${item.label}`"
          @click.stop="closeTab(item.id)"
        >
          <X :size="12" />
        </button>
      </div>
    </div>

    <div class="vben-tabbar-actions">
      <button
        type="button"
        class="vben-tab-action-btn"
        title="刷新当前页"
        aria-label="刷新当前页"
        :disabled="props.refreshing"
        @click="emit('refresh')"
      >
        <RotateCw :size="14" :class="{ 'is-spinning': props.refreshing }" />
      </button>

      <div class="vben-tab-menu-wrap">
        <button
          type="button"
          class="vben-tab-action-btn"
          title="页签操作"
          aria-label="页签操作"
          :aria-expanded="menuOpen"
          aria-haspopup="menu"
          @click="menuOpen = !menuOpen"
        >
          <ChevronDown :size="14" />
        </button>
        <div v-if="menuOpen" class="vben-tab-dropdown" role="menu">
          <button type="button" role="menuitem" @click="closeOtherTabs">关闭其他页签</button>
          <button type="button" role="menuitem" @click="closeAllTabs">关闭全部页签</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vben-tabbar {
  height: var(--vben-tabbar-h, 38px);
  background: var(--vben-bg-surface);
  border-bottom: 1px solid var(--vben-border);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 0 8px 0 12px;
  gap: 8px;
  flex-shrink: 0;
  user-select: none;
}

.vben-tabbar-scroll {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
  flex: 1;
  min-width: 0;
  height: 100%;
  padding-top: 5px;
}

.vben-tabbar-scroll::-webkit-scrollbar {
  display: none;
}

.vben-tab-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px 8px 0 0;
  font-size: var(--vben-fs-tab, 13.5px);
  font-weight: 500;
  color: var(--vben-fg-muted);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
  border: 1px solid transparent;
  border-bottom: none;
}

.vben-tab-item:hover {
  background: var(--vben-bg-hover);
  color: var(--vben-fg-strong);
}

.vben-tab-item:focus-visible {
  outline: 2px solid var(--vben-primary);
  outline-offset: -2px;
}

.vben-tab-item.is-active {
  background: var(--vben-primary-soft);
  color: var(--vben-primary);
  font-weight: 600;
  border-color: var(--vben-primary-border);
}

[data-theme="dark"] .vben-tab-item.is-active {
  background: var(--vben-bg-hover);
  color: var(--vben-fg-strong);
  border-color: var(--vben-border);
}

.vben-tab-pin {
  opacity: 0.55;
  flex-shrink: 0;
}

.vben-tab-close {
  appearance: none;
  border: none;
  background: transparent;
  color: inherit;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0.65;
  cursor: pointer;
}

.vben-tab-close:hover {
  opacity: 1;
  background: rgba(128, 128, 128, 0.2);
}

.vben-tabbar-actions {
  display: flex;
  align-items: center;
  height: 100%;
  gap: 2px;
  flex-shrink: 0;
  border-left: 1px solid var(--vben-border-soft);
  padding-left: 6px;
}

.vben-tab-action-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--vben-fg-muted);
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-tab-action-btn:hover:not(:disabled) {
  background: var(--vben-bg-hover);
  color: var(--vben-fg-strong);
}

.vben-tab-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.vben-tab-menu-wrap {
  position: relative;
}

.vben-tab-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 132px;
  padding: 4px;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: 8px;
  box-shadow: var(--vben-shadow-elevated);
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.vben-tab-dropdown button {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--vben-fg);
  text-align: left;
  font-size: 13px;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.vben-tab-dropdown button:hover {
  background: var(--vben-bg-hover);
}

.is-spinning {
  animation: vben-spin 0.8s linear infinite;
}

@keyframes vben-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 720px) {
  .vben-tabbar {
    display: none;
  }
}
</style>
