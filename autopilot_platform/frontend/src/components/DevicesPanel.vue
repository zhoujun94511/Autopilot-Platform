<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useShellStore } from "../stores/shellStore";
import { useExecStore } from "../stores/execution";
import { useAdminStore } from "../stores/adminStore";
import { useCapabilities } from "../composables/useCapabilities";
import { useDeviceBoardFilters } from "../composables/useDeviceBoardFilters";
import { PLATFORM_LABEL, PLATFORM_ORDER, normalizePlatform, platformBadgeLabel } from "../utils/deviceDisplay";
import DataPager from "./common/DataPager.vue";
import DeviceBoardCards from "./DeviceBoardCards.vue";
import DeviceBoardTable from "./DeviceBoardTable.vue";

const props = defineProps<{
  /** @deprecated 使用 embedded；兼容旧调用 */
  compact?: boolean;
  /** 嵌入 DevicesHub 单一工作区：不重复标题、不套外层卡 */
  embedded?: boolean;
}>();

const hideChromeTitle = computed(() => Boolean(props.embedded || props.compact));

const auth = useAuthStore();
const { canManageUsers } = storeToRefs(auth);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const exec = useExecStore();
const admin = useAdminStore();
const { deviceBoard, devicesVersion } = storeToRefs(exec);
const { auditFilter } = storeToRefs(admin);

const caps = useCapabilities();

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
  setPage,
  setPageSize,
  onlineTotal,
  platformChipCounts,
  groupedDevices,
  showPlatformSections,
  toggleMeta,
  applyPlatformFromSummary,
} = useDeviceBoardFilters({
  deviceBoard,
  devicesVersion,
});

const hasDeviceActions = computed(() =>
  items.value.some(
    (d) => d.can_reserve || d.can_release_reservation || d.can_manage,
  ),
);

const showViewerHint = computed(
  () =>
    caps.isProjectViewer ||
    (!caps.canManageInfra &&
      !items.value.some((d) => d.can_reserve || d.can_release_reservation)),
);

function openDeviceAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "device.";
  auditFilter.value.actor = "";
  activeTab.value = "audit";
  void admin.refreshAudits();
}
</script>

<template>
  <section class="panel" :class="{ compact: hideChromeTitle, embedded: props.embedded || props.compact }">
    <div class="panel-toolbar">
      <div class="panel-toolbar-left">
        <template v-if="!hideChromeTitle">
          <h2>设备</h2>
          <p class="panel-toolbar-desc">
            组织在线设备：占用 / 释放 / 远控不跟顶栏项目走；批跑选设备才会按本项目资源池筛选
            <button
              v-if="canManageUsers"
              type="button"
              class="linkish inline"
              @click="openDeviceAudit"
            >
              查看操作记录
            </button>
          </p>
        </template>
        <p v-if="showViewerHint" class="collab-hint">
          当前只能查看设备是否空闲。占用或释放需要更高权限。
        </p>
        <p v-else class="collab-hint">
          任务正在用的设备不能再手动占用；你占用的设备也不会被别人的任务抢走。
        </p>
      </div>
      <div class="panel-toolbar-right">
        <div class="view-toggle" role="group" aria-label="视图切换">
          <button
            type="button"
            class="view-toggle-btn"
            :class="{ active: viewMode === 'cards' }"
            title="卡片展台"
            @click.stop="viewMode = 'cards'"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
            卡片
          </button>
          <button
            type="button"
            class="view-toggle-btn"
            :class="{ active: viewMode === 'list' }"
            title="列表视图"
            @click.stop="viewMode = 'list'"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6" />
              <line x1="8" y1="12" x2="21" y2="12" />
              <line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" />
              <line x1="3" y1="12" x2="3.01" y2="12" />
              <line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
            列表
          </button>
        </div>
        <label class="toolbar-search device-search">
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input v-model="search" type="search" placeholder="搜索设备编号 / 型号 / 节点…" />
        </label>
      </div>
    </div>

    <div v-if="deviceBoard" class="device-summary-dashboard">
      <div class="summary-pill total">
        <span class="dot blue"></span>
        <span class="label">在线 {{ deviceBoard.summary.online }}</span>
      </div>
      <button
        type="button"
        class="summary-pill free clickable"
        :class="{ active: busyFilter === 'free' }"
        @click.stop="busyFilter = busyFilter === 'free' ? '' : 'free'"
      >
        <span class="dot green"></span>
        <span class="label">空闲 {{ deviceBoard.summary.free }}</span>
      </button>
      <button
        type="button"
        class="summary-pill busy clickable"
        :class="{ active: busyFilter === 'busy' }"
        @click.stop="busyFilter = busyFilter === 'busy' ? '' : 'busy'"
      >
        <span class="dot red"></span>
        <span class="label">占用 {{ deviceBoard.summary.busy }}</span>
      </button>
      <button
        v-for="(s, plat) in deviceBoard.summary.by_platform"
        :key="plat"
        type="button"
        class="summary-pill platform clickable"
        :class="[
          String(plat).toLowerCase(),
          { active: platformFilter === normalizePlatform(String(plat)) },
        ]"
        :title="`筛选 ${platformBadgeLabel(String(plat))}`"
        @click.stop="applyPlatformFromSummary(String(plat))"
      >
        <span class="dot"></span>
        <span class="label">
          <strong>{{ platformBadgeLabel(String(plat)) }}</strong>
          {{ s.free }}/{{ s.total }} 空闲
        </span>
      </button>
    </div>

    <div class="filter-rows">
      <div class="filter-chips" role="tablist" aria-label="平台筛选">
        <button
          type="button"
          class="filter-chip"
          :class="{ active: platformFilter === 'all' }"
          @click="platformFilter = 'all'"
        >
          全部
          <span class="chip-count">{{ platformChipCounts.all }}</span>
        </button>
        <button
          v-for="key in PLATFORM_ORDER"
          :key="key"
          type="button"
          class="filter-chip platform-chip"
          :class="[key, { active: platformFilter === key }]"
          @click="platformFilter = key"
        >
          {{ PLATFORM_LABEL[key] }}
          <span class="chip-count">{{ platformChipCounts[key] }}</span>
        </button>
      </div>
      <div class="filter-chips" role="tablist" aria-label="设备占用筛选">
        <button
          type="button"
          class="filter-chip"
          :class="{ active: busyFilter === '' }"
          @click="busyFilter = ''"
        >
          全部状态
        </button>
        <button
          type="button"
          class="filter-chip"
          :class="{ active: busyFilter === 'free' }"
          @click="busyFilter = 'free'"
        >
          空闲
        </button>
        <button
          type="button"
          class="filter-chip"
          :class="{ active: busyFilter === 'busy' }"
          @click="busyFilter = 'busy'"
        >
          占用中
        </button>
      </div>
    </div>

    <div v-if="!items.length && hasLoaded" class="empty-shelf">
      <div v-if="!onlineTotal" class="empty-guide">
        <p class="empty-guide-title">暂无在线设备</p>
        <template v-if="caps.canOps">
          <p class="hint">请确认下面几项后，再点刷新：</p>
          <ol class="empty-guide-steps">
            <li>管理台已启动</li>
            <li>本机执行程序已打开</li>
            <li>手机已授权连接</li>
          </ol>
        </template>
        <p v-else class="hint">暂无可用设备，请联系管理员接入设备后再发起批跑。</p>
      </div>
      <p v-else class="empty-filter-hint">无匹配设备，请调整平台、占用筛选或搜索</p>
    </div>

    <template v-else-if="items.length && viewMode === 'cards'">
      <DeviceBoardCards
        :groups="groupedDevices"
        :show-platform-sections="showPlatformSections"
        :expanded-meta="expandedMeta"
        @toggle-meta="toggleMeta"
      />
    </template>

    <DeviceBoardTable
      v-else-if="items.length"
      :items="items"
      :has-device-actions="hasDeviceActions"
    />

    <DataPager
      v-if="total > 0"
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
.collab-hint {
  margin: 0.35rem 0 0;
  max-width: 40rem;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
  white-space: normal;
  overflow-wrap: break-word;
}

.collab-hint strong {
  color: var(--text);
  font-weight: 650;
}

.panel-toolbar-desc .linkish {
  border: none;
  background: none;
  padding: 0 0.15rem;
  color: var(--accent, #2563eb);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.filter-rows {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin-bottom: 1rem;
}

.view-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  padding: 0.15rem;
  background: var(--surface-secondary);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}

.view-toggle-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.72rem;
  font-weight: 650;
  padding: 0.3rem 0.55rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  transition: var(--transition);
}

.view-toggle-btn:hover {
  color: var(--text);
  background: var(--action-hover);
}

.view-toggle-btn.active {
  background: var(--action-selected);
  color: var(--accent-text);
}

.device-summary-dashboard {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-bottom: 0.85rem;
}

.summary-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.8rem;
  border-radius: 999px;
  background-color: var(--btn-bg);
  border: 1px solid var(--line);
  font-size: 0.78rem;
  font-weight: 550;
  color: var(--text);
}

.summary-pill.clickable {
  appearance: none;
  font: inherit;
  cursor: pointer;
  transition: var(--transition);
}

.summary-pill.clickable:hover {
  border-color: var(--accent);
}

.summary-pill.clickable.active {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
  background: var(--action-selected);
}

.summary-pill .label strong {
  font-weight: 750;
  margin-right: 0.2rem;
}

.summary-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.summary-pill .dot.blue {
  background-color: var(--accent);
}
.summary-pill .dot.green {
  background-color: var(--ok);
}
.summary-pill .dot.red {
  background-color: var(--bad);
}

.summary-pill.android {
  background-color: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
  color: var(--ok-soft-fg);
}
.summary-pill.android .dot {
  background-color: var(--ok);
}

.summary-pill.ios {
  background-color: var(--purple-soft-bg);
  border-color: var(--purple-soft-border);
  color: var(--purple-soft-fg);
}
.summary-pill.ios .dot {
  background-color: var(--purple-soft-fg);
}

.summary-pill.web {
  background-color: var(--info-soft-bg);
  border-color: var(--info-soft-border);
  color: var(--info-soft-fg);
}
.summary-pill.web .dot {
  background-color: var(--accent);
}

.chip-count {
  margin-left: 0.25rem;
  opacity: 0.75;
  font-variant-numeric: tabular-nums;
}

.filter-chip.platform-chip.android.active {
  background: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
  color: var(--ok-soft-fg);
}

.filter-chip.platform-chip.ios.active {
  background: var(--purple-soft-bg);
  border-color: var(--purple-soft-border);
  color: var(--purple-soft-fg);
}

.filter-chip.platform-chip.web.active {
  background: var(--info-soft-bg);
  border-color: var(--info-soft-border);
  color: var(--info-soft-fg);
}

.empty-shelf {
  padding: 1.5rem 1rem;
  border: 1px dashed var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-soft);
  min-width: 0;
}

.empty-filter-hint {
  margin: 0;
  text-align: center;
  color: var(--muted);
  font-size: 0.88rem;
  white-space: normal;
}

.empty-guide {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.45rem;
  text-align: left;
  max-width: 36rem;
  width: 100%;
  margin: 0 auto;
  min-width: 0;
  line-height: 1.5;
}
.empty-guide-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 650;
  color: var(--text);
}
.empty-guide .hint {
  margin: 0;
  opacity: 0.9;
  font-size: 0.86rem;
  white-space: normal;
  overflow-wrap: break-word;
}
.empty-guide-steps {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0;
  padding-left: 1.35rem;
  color: var(--muted);
  font-size: 0.86rem;
  line-height: 1.5;
}
.empty-guide-steps li {
  display: list-item;
  white-space: normal;
}

.panel.compact,
.panel.embedded {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
}

.panel.embedded .panel-toolbar-right {
  margin-left: auto;
}

.device-search {
  min-width: 16.5rem;
  max-width: 22rem;
  flex: 0 0 16.5rem;
}

.device-search input {
  min-width: 12rem;
}

.compact-title {
  margin: 0 !important;
  font-size: 0.95rem !important;
  font-weight: 700;
  color: var(--text);
}
</style>
