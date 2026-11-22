<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useExecStore } from "../stores/execution";
import { useAdminStore } from "../stores/adminStore";
import { useCapabilities } from "../composables/useCapabilities";
import { useDeviceBoardFilters } from "../composables/useDeviceBoardFilters";
import { PLATFORM_LABEL, PLATFORM_ORDER } from "../utils/deviceDisplay";
import { canObserveRemote, canOpenRemote } from "../composables/useRemoteSession";
import DataPager from "./common/DataPager.vue";
import DeviceBoardCards from "./DeviceBoardCards.vue";
import DeviceBoardTable from "./DeviceBoardTable.vue";
import ApSelect from "./common/ApSelect.vue";

const props = defineProps<{
  /** @deprecated 使用 embedded；兼容旧调用 */
  compact?: boolean;
  /** 嵌入 DevicesHub 单一工作区：不重复标题、不套外层卡 */
  embedded?: boolean;
}>();

const hideChromeTitle = computed(() => Boolean(props.embedded || props.compact));

const auth = useAuthStore();
const { canManageUsers, user } = storeToRefs(auth);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const exec = useExecStore();
const admin = useAdminStore();
const { deviceBoard, devicesVersion } = storeToRefs(exec);
const { auditFilter } = storeToRefs(admin);

const caps = useCapabilities();
const platformOptions = [{ value: "all", label: "全部平台" }, ...PLATFORM_ORDER.map((key) => ({ value: key, label: PLATFORM_LABEL[key] }))];
const busyOptions = [{ value: "", label: "全部状态" }, { value: "free", label: "空闲" }, { value: "busy", label: "占用中" }];

const {
  search,
  busyFilter,
  platformFilter,
  viewMode,
  expandedMeta,
  items,
  total,
  page,
  pageSize,
  loading,
  hasLoaded,
  error,
  refreshing,
  reload,
  setPage,
  setPageSize,
  groupedDevices,
  showPlatformSections,
  toggleMeta,
} = useDeviceBoardFilters({
  deviceBoard,
  devicesVersion,
});

function clearDeviceFilter() {
  search.value = "";
  busyFilter.value = "";
  platformFilter.value = "all";
}

const hasDeviceActions = computed(() =>
  items.value.some(
    (d) => d.can_reserve || d.can_release_reservation || d.can_manage
      || canOpenRemote(d, user.value) || canObserveRemote(d, user.value),
  ),
);
const hasFilters = computed(() => Boolean(search.value.trim() || busyFilter.value || platformFilter.value !== "all"));

function openDeviceAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "device.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}
</script>

<template>
  <section class="device-board" aria-label="在线设备">
    <header v-if="!hideChromeTitle" class="page-hero">
      <h2>在线设备</h2>
      <button v-if="canManageUsers" type="button" @click="openDeviceAudit">查看操作记录</button>
    </header>

    <div class="device-toolbar">
      <div class="device-filters" role="group" aria-label="设备筛选">
        <input
          v-model="search"
          class="device-search"
          type="search"
          name="device-search"
          aria-label="搜索设备"
          placeholder="搜索编号、型号或节点…"
        />
        <div class="device-select-wrap">
          <ApSelect v-model="platformFilter" name="device-platform" aria-label="平台" :options="platformOptions" />
        </div>
        <div class="device-select-wrap">
          <ApSelect v-model="busyFilter" name="device-busy" aria-label="占用状态" :options="busyOptions" />
        </div>
        <button v-if="hasFilters" type="button" class="vben-reset-btn" @click="clearDeviceFilter">重置</button>
      </div>
      <div class="view-toggle" role="group" aria-label="设备视图">
        <button v-for="[mode, label] in [['cards', '卡片'], ['list', '列表']] as const"
          :key="mode" type="button" :aria-pressed="viewMode === mode" @click="viewMode = mode">
          {{ label }}
        </button>
      </div>
    </div>

    <div v-if="error" class="device-load-error" role="alert">
      <span>无法加载在线设备。{{ error }}</span>
      <button type="button" class="small" @click="reload(false)">重试</button>
    </div>
    <p v-if="refreshing" class="device-refresh-status" role="status">正在刷新设备…</p>
    <div class="device-results" :class="{ 'device-results-cards': viewMode === 'cards' && items.length }" :aria-busy="loading">
      <template v-if="!error || items.length">
        <div v-if="!items.length && hasLoaded" class="empty-state devices-empty">
          <p class="empty-title">{{ hasFilters ? "无匹配设备" : "暂无设备" }}</p>
          <template v-if="!hasFilters">
            <p class="empty-desc">{{ caps.canOps ? "检查执行节点和设备连接" : "请联系管理员" }}</p>
            <button type="button" class="small" @click="reload(false)">刷新</button>
          </template>
        </div>
        <p v-else-if="!hasLoaded" class="empty-state devices-empty" role="status">正在加载设备…</p>
        <DeviceBoardCards
          v-else-if="items.length && viewMode === 'cards'"
          :groups="groupedDevices"
          :show-platform-sections="showPlatformSections"
          :expanded-meta="expandedMeta"
          @toggle-meta="toggleMeta"
        />
        <DeviceBoardTable
          v-else-if="items.length"
          class="device-table"
          :items="items"
          :has-device-actions="hasDeviceActions"
          tabindex="0"
          role="region"
          aria-label="在线设备列表"
        />
      </template>
    </div>
    <DataPager
      v-if="total > 0"
      class="device-pager"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />
  </section>
</template>

<style scoped>
.device-board {
  min-width: 0;
}

.device-toolbar,
.device-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
}

.device-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--vben-border-soft);
}

.device-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  flex: 1 1 420px;
  min-width: 0;
}

.device-search {
  width: 240px;
  height: 34px;
  min-width: 0;
  flex: 0 1 240px;
  border-radius: 6px;
}

.device-select-wrap {
  flex: 0 0 144px;
  width: 144px;
}

.vben-reset-btn {
  appearance: none;
  border: 1px solid var(--vben-border);
  background: var(--vben-bg-surface);
  color: var(--vben-fg);
  height: 34px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.vben-reset-btn:hover {
  border-color: var(--vben-primary);
  color: var(--vben-primary);
}

.view-toggle {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface-secondary);
}

.view-toggle button {
  min-height: 28px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
}

.view-toggle [aria-pressed="true"] {
  background: var(--panel);
  color: var(--accent-text);
  border-color: var(--line);
}

.device-results-cards {
  padding: 12px 20px 16px;
}

.devices-empty {
  min-height: 148px;
  margin: 0;
  border: 0;
}

.device-table {
  margin: 0;
  border: 0;
  border-radius: 0;
}

.device-table:focus-visible {
  outline-offset: -2px;
}

.device-pager {
  margin: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--line-soft);
}

.device-load-error {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  color: var(--danger-soft-fg);
  padding: 12px 20px;
}

.device-refresh-status {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

@media (max-width: 620px) {
  .device-toolbar,
  .device-results-cards,
  .device-pager,
  .device-load-error {
    padding-inline: 12px;
  }
  .device-filters {
    width: 100%;
  }
  .device-search {
    width: 100%;
    flex-basis: 100%;
  }
}
</style>
