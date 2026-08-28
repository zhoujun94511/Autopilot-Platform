<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useShellStore } from "../stores/shellStore";
import { useExecStore } from "../stores/execution";
import { useContextStore } from "../stores/context";
import { useCapabilities } from "../composables/useCapabilities";
import { notify, showCopyDialog } from "../composables/useNotify";
import { usePagedList } from "../composables/usePagedList";
import { listRunnersPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { displayName, platformBadgeLabel, runnerSourceLabel, runnerDetailHeartbeatLabel, runnerHeartbeatHint, runnerHeartbeatTitle, runnerOnlineBadgeClass, runnerOnlineBadgeLabel } from "../utils/deviceDisplay";
import {
  filterInventoryByStatus,
  isInventoryDeviceRegistered,
  partitionCheckedUdids,
  type InventoryStatusFilter,
} from "../utils/inventoryRegister";
import {
  api,
  apiErrorMessage,
  type ManagedRunnerStatus,
  type Runner,
  type RunnerDeviceInventory,
  type RunnerDeviceSelectionResult,
  type RunnerInventoryDevice,
  type RunnerProvisionResult,
} from "../api";
import DataPager from "./common/DataPager.vue";
import ApModal from "./ApModal.vue";
import ApSelect from "./common/ApSelect.vue";

const props = defineProps<{
  compact?: boolean;
  embedded?: boolean;
}>();

const hideChromeTitle = computed(() => Boolean(props.embedded || props.compact));

const shell = useShellStore();
const exec = useExecStore();
const context = useContextStore();
const { runnersListVersion, managedRunner, runners, devices } = storeToRefs(exec);
const { filterOrgId, orgs } = storeToRefs(context);
const registerOrgId = ref("");
const provisionOrgId = ref("");

const caps = useCapabilities();
const selectedRunner = ref<Runner | null>(null);
const showManagedLogs = ref(false);
const runnerFilter = ref<"online" | "all" | "offline">("online");
const deviceManagerOpen = ref(false);
const deviceManagerLoading = ref(false);
const deviceManagerSaving = ref(false);
const deviceInventory = ref<RunnerDeviceInventory | null>(null);
const checkedUdids = ref<string[]>([]);
const deviceActionResult = ref("");
const NESTED_DEVICE_PAGE_SIZE = 20;
const detailDevicePage = ref(1);
const detailDevicePageSize = ref(NESTED_DEVICE_PAGE_SIZE);
const inventoryPage = ref(1);
const inventoryPageSize = ref(NESTED_DEVICE_PAGE_SIZE);
const inventoryQuery = ref("");
const inventoryStatusFilter = ref<InventoryStatusFilter>("pending");
const provisionOpen = ref(false);
const provisionSaving = ref(false);
const provisionRunnerId = ref("");
const provisionError = ref("");

const list = usePagedList<Runner>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listRunnersPage({
      page,
      pageSize,
    }),
});

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

watch(runnersListVersion, () => void reload(false));
void reload(true);

const canManageRunners = computed(() => caps.canManageRunners);
const managed = computed(() => managedRunner.value);
const managedEnabled = computed(() => Boolean(managed.value?.enabled));
const managedRunning = computed(() => Boolean(managed.value?.running));

const runnersOnlineCount = computed(
  () => (runners.value || []).filter((r: Runner) => r.online).length,
);
const runnersOfflineCount = computed(
  () => (runners.value || []).filter((r: Runner) => !r.online).length,
);

const managedRunnerId = computed(() => (managed.value?.runner_id || "managed-local").trim());

const filteredRunners = computed(() => {
  const listItems = items.value || [];
  if (runnerFilter.value === "online") return listItems.filter((r) => r.online);
  if (runnerFilter.value === "offline") return listItems.filter((r) => !r.online);
  return listItems;
});

const RUNNER_FILTERS = [
  { value: "online" as const, label: "在线" },
  { value: "offline" as const, label: "已离线" },
  { value: "all" as const, label: "全部" },
];

function deviceCount(runnerId: string) {
  return devices.value.filter((d: { runner_id?: string }) => d.runner_id === runnerId).length;
}

const detailDevices = computed(() => {
  const r = selectedRunner.value;
  if (!r) return [];
  return devices.value.filter((d: { runner_id?: string }) => d.runner_id === r.runner_id);
});

function clampPage(total: number, page: number, pageSize: number) {
  const pages = Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, pageSize)));
  return Math.min(Math.max(1, page), pages);
}

function slicePage<T>(rows: T[], page: number, pageSize: number): T[] {
  const size = Math.max(1, pageSize);
  const start = (clampPage(rows.length, page, size) - 1) * size;
  return rows.slice(start, start + size);
}

const pagedDetailDevices = computed(() =>
  slicePage(detailDevices.value, detailDevicePage.value, detailDevicePageSize.value),
);

function setDetailDevicePage(next: number) {
  detailDevicePage.value = clampPage(
    detailDevices.value.length,
    next,
    detailDevicePageSize.value,
  );
}

function setDetailDevicePageSize(next: number) {
  detailDevicePageSize.value = Math.max(1, next);
  detailDevicePage.value = 1;
}

function openDetail(r: Runner) {
  selectedRunner.value = r;
  detailDevicePage.value = 1;
}
function closeDetail() {
  selectedRunner.value = null;
}
function formatTime(iso?: string | null) {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function occupancyKindLabel(kind?: string) {
  if (kind === "job") return "任务占用";
  if (kind === "reservation") return "设备预占";
  return "占用";
}

function runnerPresenceContext(r: Runner) {
  return {
    isManagedRow: isManagedRow(r),
    managedRunning: managedRunning.value,
  };
}

function visibleCapabilities(r: Runner) {
  return (r.capabilities || []).slice(0, 4);
}

function hiddenCapabilityCount(r: Runner) {
  return Math.max(0, (r.capabilities || []).length - 4);
}

function isManagedRow(r: Runner) {
  return managed.value?.runner_id && r.runner_id === managed.value.runner_id;
}

function inventoryHaystack(d: RunnerInventoryDevice) {
  return [d.udid, d.name, d.model, d.platform, d.os_version].join(" ").toLowerCase();
}

function deviceIsRegistered(d: RunnerInventoryDevice) {
  return isInventoryDeviceRegistered(deviceInventory.value, d);
}

const searchedInventory = computed(() => {
  const all = deviceInventory.value?.devices || [];
  const q = inventoryQuery.value.trim().toLowerCase();
  if (!q) return all;
  return all.filter((d) => inventoryHaystack(d).includes(q));
});

const filteredInventory = computed(() =>
  filterInventoryByStatus(
    searchedInventory.value,
    deviceInventory.value,
    inventoryStatusFilter.value,
  ),
);

const pagedInventory = computed(() =>
  slicePage(filteredInventory.value, inventoryPage.value, inventoryPageSize.value),
);

const inventorySelectable = computed(() =>
  filteredInventory.value.filter((d) => !d.rejection_reason),
);

const pendingInventoryCount = computed(
  () =>
    filterInventoryByStatus(searchedInventory.value, deviceInventory.value, "pending").length,
);
const registeredInventoryCount = computed(
  () =>
    filterInventoryByStatus(searchedInventory.value, deviceInventory.value, "registered")
      .length,
);

const checkedPartition = computed(() =>
  partitionCheckedUdids(deviceInventory.value, checkedUdids.value),
);
const checkedPendingUdids = computed(() => checkedPartition.value.pending);
const checkedRegisteredUdids = computed(() => checkedPartition.value.registered);

const allInventoryChecked = computed(() => {
  const candidates = inventorySelectable.value;
  return candidates.length > 0 && candidates.every((d) => checkedUdids.value.includes(d.udid));
});

const inventorySelectAllLabel = computed(() => {
  if (allInventoryChecked.value) return "取消全选";
  if (inventoryStatusFilter.value === "registered") return "全选已注册";
  if (inventoryStatusFilter.value === "pending") return "全选待注册";
  return "全选可用设备";
});

function setInventoryPage(next: number) {
  inventoryPage.value = clampPage(
    filteredInventory.value.length,
    next,
    inventoryPageSize.value,
  );
}

function setInventoryPageSize(next: number) {
  inventoryPageSize.value = Math.max(1, next);
  inventoryPage.value = 1;
}

watch(inventoryQuery, () => {
  inventoryPage.value = 1;
});
watch(inventoryStatusFilter, () => {
  inventoryPage.value = 1;
  checkedUdids.value = [];
});
watch(filteredInventory, (rows) => {
  inventoryPage.value = clampPage(rows.length, inventoryPage.value, inventoryPageSize.value);
});
watch(detailDevices, (rows) => {
  detailDevicePage.value = clampPage(rows.length, detailDevicePage.value, detailDevicePageSize.value);
});

function toggleInventoryDevice(udid: string, checked: boolean) {
  const next = new Set(checkedUdids.value);
  if (checked) next.add(udid);
  else next.delete(udid);
  checkedUdids.value = [...next];
}

function toggleAllInventory() {
  const pool = inventorySelectable.value;
  if (allInventoryChecked.value) {
    const drop = new Set(pool.map((d) => d.udid));
    checkedUdids.value = checkedUdids.value.filter((udid) => !drop.has(udid));
    return;
  }
  const next = new Set(checkedUdids.value);
  for (const d of pool) next.add(d.udid);
  checkedUdids.value = [...next];
}

function findRunner(runnerId: string): Runner | undefined {
  const id = (runnerId || "").trim();
  if (!id) return undefined;
  return (
    (runners.value || []).find((r) => r.runner_id === id) ||
    (items.value || []).find((r) => r.runner_id === id)
  );
}

function orgLabel(orgId: string): string {
  const oid = (orgId || "").trim();
  if (!oid) return "";
  const hit = (orgs.value || []).find((o) => o.id === oid);
  return hit?.name ? `${hit.name}（${oid}）` : oid;
}

function defaultOrgId(preferred = ""): string {
  const pref = preferred.trim();
  if (pref) return pref;
  const bar = filterOrgId.value.trim();
  if (bar) return bar;
  if ((orgs.value || []).length === 1) return orgs.value[0].id;
  return "";
}

const orgOptions = computed(() =>
  (orgs.value || []).map((o) => ({
    value: o.id,
    label: o.name ? `${o.name}（${o.id}）` : o.id,
  })),
);

const boundDeviceOrgId = computed(() => {
  const inventory = deviceInventory.value;
  if (!inventory) return "";
  return (
    (inventory.org_id || "").trim() ||
    (findRunner(inventory.runner_id)?.org_id || "").trim()
  );
});

const willStartManagedOnRegister = computed(() => {
  const inventory = deviceInventory.value;
  if (!inventory) return false;
  return (
    inventory.runner_id === (managed.value?.runner_id || "managed-local") &&
    !managedRunning.value
  );
});

const needsOrgOnRegister = computed(
  () =>
    !caps.canOps &&
    !boundDeviceOrgId.value &&
    orgOptions.value.length > 0,
);

function resolvedRegisterOrgId(): string {
  return boundDeviceOrgId.value || registerOrgId.value.trim();
}

function initRegisterOrg(runnerId: string, inventoryOrgId = "") {
  registerOrgId.value = defaultOrgId(
    (inventoryOrgId || "").trim() || (findRunner(runnerId)?.org_id || "").trim(),
  );
}

async function loadDeviceInventory(runnerId: string, probe = false) {
  deviceManagerLoading.value = true;
  deviceActionResult.value = "";
  try {
    const path = probe
      ? "/api/v1/runners/managed/device-probe"
      : `/api/v1/runners/${encodeURIComponent(runnerId)}/device-inventory`;
    deviceInventory.value = await api<RunnerDeviceInventory>(path, {
      method: probe ? "POST" : "GET",
    });
    checkedUdids.value = [];
    inventoryQuery.value = "";
    inventoryStatusFilter.value = "pending";
    inventoryPage.value = 1;
    initRegisterOrg(deviceInventory.value.runner_id, deviceInventory.value.org_id);
    deviceManagerOpen.value = true;
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  } finally {
    deviceManagerLoading.value = false;
  }
}

async function applyDeviceSelection(action: "register" | "unregister") {
  const inventory = deviceInventory.value;
  if (!inventory || !checkedUdids.value.length) {
    deviceActionResult.value =
      inventoryStatusFilter.value === "registered"
        ? "请勾选要取消注册的设备"
        : "请勾选待注册设备";
    return;
  }
  const selected = checkedUdids.value;
  const split = partitionCheckedUdids(inventory, selected);
  const udids = action === "register" ? split.pending : split.registered;
  if (!udids.length) {
    deviceActionResult.value =
      action === "register" ? "所选设备已注册，无需重复登记" : "所选设备尚未注册";
    return;
  }
  const orgId = resolvedRegisterOrgId();
  if (action === "register" && needsOrgOnRegister.value && !orgId) {
    deviceActionResult.value = "请选择本机节点的归属组织";
    return;
  }
  deviceManagerSaving.value = true;
  try {
    if (action === "register" && needsOrgOnRegister.value && orgId) {
      await api(`/api/v1/runners/${encodeURIComponent(inventory.runner_id)}/scope`, {
        method: "PATCH",
        body: JSON.stringify({ org_id: orgId }),
      });
    }
    const out = await api<RunnerDeviceSelectionResult>(
      `/api/v1/runners/${encodeURIComponent(inventory.runner_id)}/device-selection`,
      {
        method: "PATCH",
        body: JSON.stringify({ action, udids }),
      },
    );
    const rejected = Object.entries(out.rejected || {});
    deviceActionResult.value = [
      action === "register"
        ? `已注册 ${out.registered.length} 台`
        : `已取消 ${out.unregistered.length} 台`,
      rejected.length ? `拒绝 ${rejected.length} 台：${rejected.map(([u, r]) => `${u}（${r}）`).join("；")}` : "",
    ]
      .filter(Boolean)
      .join("。");
    if (action === "register" && willStartManagedOnRegister.value) {
      const started = await api<ManagedRunnerStatus>("/api/v1/runners/managed/start", {
        method: "POST",
        body: orgId ? JSON.stringify({ org_id: orgId }) : undefined,
      });
      managedRunner.value = started;
    }
    deviceInventory.value = await api<RunnerDeviceInventory>(
      `/api/v1/runners/${encodeURIComponent(inventory.runner_id)}/device-inventory`,
    );
    checkedUdids.value = [];
    await shell.refreshScopes(["runners", "devices", "managed-runner"]);
    const registeredOk =
      action === "register" && out.registered.length > 0 && rejected.length === 0;
    if (registeredOk) {
      const hints = [
        deviceActionResult.value,
        willStartManagedOnRegister.value
          ? "已尝试启动本机托管，节点上线后即可调度"
          : caps.canOps
            ? "若在线设备仍看不到，请确认节点在线且心跳正常"
            : "若在线设备仍看不到，请确认节点在线且已绑定组织",
      ];
      notify(hints.filter(Boolean).join("。"), "success");
      deviceManagerOpen.value = false;
      deviceActionResult.value = "";
    }
  } catch (e) {
    deviceActionResult.value = apiErrorMessage(e);
  } finally {
    deviceManagerSaving.value = false;
  }
}

function openProvision() {
  provisionRunnerId.value = `runner-${Math.random().toString(36).slice(2, 8)}`;
  provisionOrgId.value = defaultOrgId();
  provisionError.value = "";
  provisionOpen.value = true;
}

async function provisionRunner() {
  const runnerId = provisionRunnerId.value.trim();
  const orgId = provisionOrgId.value.trim();
  provisionError.value = "";
  if (!runnerId || !orgId) {
    provisionError.value = "请选择归属组织并填写节点 ID";
    return;
  }
  provisionSaving.value = true;
  try {
    const out = await api<RunnerProvisionResult>("/api/v1/runners/provision", {
      method: "POST",
      body: JSON.stringify({ runner_id: runnerId, org_id: orgId, project_ids: [] }),
    });
    provisionOpen.value = false;
    await showCopyDialog(out.command, {
      title: "远程 Runner 启动命令",
      text: "仅显示一次。请在插手机的那台电脑上执行，不要在 Platform 服务器上执行。关窗口会掉线，机房请做成开机自启。之后可在 Web 管理该节点设备。",
    });
    await shell.refreshScopes(["runners"]);
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  } finally {
    provisionSaving.value = false;
  }
}
</script>

<template>
  <section class="panel" :class="{ compact: hideChromeTitle, embedded: props.embedded || props.compact }">
    <div class="panel-header-row">
      <h2 v-if="!hideChromeTitle">执行节点</h2>
      <div class="header-actions">
        <button
          v-if="canManageRunners"
          type="button"
          class="primary small"
          @click="openProvision"
          title="预配节点并生成一次性启动命令"
        >
          接入新节点
        </button>
        <button
          type="button"
          class="small"
          @click="shell.refreshForTab('devices')"
          title="刷新节点和设备状态"
        >
          刷新
        </button>
      </div>
    </div>

    <details v-if="canManageRunners" class="managed-box" :open="managedEnabled">
      <summary class="managed-summary">
        <span class="managed-summary-leading">
          <strong>Platform 同机托管</strong>
          <span
            class="status-badge"
            :class="managedRunning ? 'status-succeeded' : managedEnabled ? 'status-failed' : ''"
          >
            {{ !managedEnabled ? "未启用" : managedRunning ? "运行中" : "未运行" }}
          </span>
        </span>
        <span v-if="managedRunning && managed?.pid" class="mono muted-chip">PID {{ managed.pid }}</span>
        <span v-if="managed?.runner_id" class="mono muted-chip">{{ managed.runner_id }}</span>
      </summary>
      <div class="managed-head">
        <div class="managed-actions">
          <button
            v-if="managedEnabled"
            type="button"
            class="primary small"
            :disabled="deviceManagerLoading"
            @click="loadDeviceInventory(managed?.runner_id || 'managed-local', true)"
          >
            管理测试设备
          </button>
          <button
            v-if="managedEnabled"
            type="button"
            class="small"
            :disabled="managedRunning"
            title="在这台电脑上启动执行程序"
            @click="exec.onStartManagedRunner"
          >
            启动本机托管
          </button>
          <button
            v-if="managedEnabled"
            type="button"
            class="danger small"
            :disabled="!managedRunning"
            @click="exec.onStopManagedRunner"
          >
            停止
          </button>
          <button
            v-if="managedEnabled"
            type="button"
            class="small"
            :disabled="!managed?.log_tail?.length"
            @click="showManagedLogs = !showManagedLogs"
          >
            {{ showManagedLogs ? "收起日志" : "日志" }}
          </button>
        </div>
      </div>
      <p v-if="!managedEnabled" class="managed-hint">
        未启用：设置 <code>MC_ALLOW_MANAGED_RUNNER=1</code> 且 Platform 绑定 loopback。
      </p>
      <p v-if="managed?.last_error" class="managed-error">最近错误：{{ managed.last_error }}</p>
      <pre v-if="showManagedLogs && managed?.log_tail?.length" class="managed-log">{{ managed.log_tail.join("\n") }}</pre>
    </details>

    <div class="runner-list-toolbar">
      <div class="filter-chips runner-filter-chips" role="tablist" aria-label="执行节点筛选">
        <button
          v-for="f in RUNNER_FILTERS"
          :key="f.value"
          type="button"
          role="tab"
          class="filter-chip"
          :class="{ active: runnerFilter === f.value }"
          :aria-selected="runnerFilter === f.value"
          @click="runnerFilter = f.value"
        >
          {{ f.label }}
          <span v-if="f.value === 'online' && runnersOnlineCount" class="chip-count">{{ runnersOnlineCount }}</span>
          <span v-else-if="f.value === 'offline' && runnersOfflineCount" class="chip-count muted">{{ runnersOfflineCount }}</span>
        </button>
      </div>
      <button
        v-if="canManageRunners"
        type="button"
        class="maintenance-action"
        @click="exec.onReclaimStale"
        title="仅处理超时后仍卡住的任务"
      >
        回收超时任务
      </button>
    </div>

    <div v-if="filteredRunners.length" class="table-wrap runner-table-wrap">
      <table class="runner-table">
        <thead>
          <tr>
            <th>节点</th>
            <th>状态与心跳</th>
            <th>在线设备</th>
            <th>能力</th>
            <th>令牌</th>
            <th v-if="canManageRunners" class="actions-col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in filteredRunners"
            :key="r.runner_id"
            class="runner-row"
            :class="{ managed: isManagedRow(r) }"
          >
            <td class="runner-identity">
              <button type="button" class="linkish-id" @click="openDetail(r)" title="查看节点详情与设备">
                {{ r.runner_id }}
              </button>
              <span
                class="pill source-pill"
                :class="{ ok: isManagedRow(r) && managedRunning }"
              >{{ runnerSourceLabel(r.registration_source) }}</span>
              <small>{{ r.hostname || "未上报主机名" }}</small>
            </td>
            <td class="runner-state-cell">
              <div class="runner-state-stack">
                <span
                  class="status-badge"
                  :class="runnerOnlineBadgeClass(r, runnerPresenceContext(r))"
                >
                  {{ runnerOnlineBadgeLabel(r, runnerPresenceContext(r)) }}
                </span>
                <span class="last-seen" :title="runnerHeartbeatTitle(r.last_heartbeat_at)">
                  {{ runnerHeartbeatHint(r, runnerPresenceContext(r)) }}
                </span>
              </div>
            </td>
            <td class="mono device-count-cell">{{ deviceCount(r.runner_id) }} 台</td>
            <td>
              <div class="capabilities-tags" :title="(r.capabilities || []).join(', ')">
                <span v-for="cap in visibleCapabilities(r)" :key="cap" class="cap-tag">{{ cap }}</span>
                <span v-if="hiddenCapabilityCount(r)" class="cap-more">+{{ hiddenCapabilityCount(r) }}</span>
                <span v-if="!r.capabilities || !r.capabilities.length">-</span>
              </div>
            </td>
            <td>
              <span class="token-state" :class="{ issued: r.has_token }">
                {{ r.has_token ? "已签发" : "未签发" }}
              </span>
            </td>
            <td v-if="canManageRunners" class="actions-col">
              <div class="runner-actions">
                <button
                  type="button"
                  class="small quiet-action"
                  @click="loadDeviceInventory(r.runner_id)"
                >
                  管理设备
                </button>
                <button
                  type="button"
                  class="small quiet-action"
                  @click="exec.onIssueRunnerToken(r.runner_id)"
                >
                  {{ r.has_token ? "轮换令牌" : "签发令牌" }}
                </button>
                <button
                  type="button"
                  class="small danger-link"
                  @click="exec.onDeregisterRunner(r)"
                  :title="
                    isManagedRow(r)
                      ? '注销登记；若要停进程请先点「停止」'
                      : '远程节点仅支持注销登记，无法由网页杀远端进程'
                  "
                >
                  注销
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-else-if="hasLoaded" class="runner-empty-panel">
      <div class="empty-guide">
        <template v-if="runnerFilter === 'online' && runnersOfflineCount > 0">
          <p>当前无在线执行节点。</p>
          <p class="hint">
            <button type="button" class="linkish-inline" @click="runnerFilter = 'offline'">
              查看离线节点 ({{ runnersOfflineCount }})
            </button>
          </p>
        </template>
        <template v-else-if="runnerFilter === 'offline'">
          <p>暂无离线注册记录。</p>
        </template>
        <template v-else-if="!items.length">
          <p>暂无可用的执行节点。</p>
          <p v-if="canManageRunners" class="hint">使用上方「接入新节点」或本机托管。</p>
          <p v-else class="hint">请联系管理员接入后再发起批跑。</p>
        </template>
        <template v-else>
          <p>无匹配节点。</p>
        </template>
      </div>
    </section>

    <DataPager
      v-if="total > 0 && (runnerFilter === 'all' || filteredRunners.length > 0)"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />

    <Teleport to="body">
      <div v-if="selectedRunner" class="drawer-mask" @click="closeDetail">
        <aside class="drawer" @click.stop>
          <header class="drawer-head">
            <div class="drawer-head-main">
              <h3 class="drawer-title mono">{{ selectedRunner.runner_id }}</h3>
              <span
                class="status-badge"
                :class="runnerOnlineBadgeClass(selectedRunner, runnerPresenceContext(selectedRunner))"
              >
                {{ runnerOnlineBadgeLabel(selectedRunner, runnerPresenceContext(selectedRunner)) }}
              </span>
              <span
                class="pill source-pill"
                :class="{ ok: isManagedRow(selectedRunner) && managedRunning }"
              >{{ runnerSourceLabel(selectedRunner.registration_source) }}</span>
            </div>
            <button type="button" class="icon-btn" @click="closeDetail" aria-label="关闭详情">✕</button>
          </header>
          <div class="drawer-body">
            <dl class="detail-grid">
              <dt>主机名</dt>
              <dd>{{ selectedRunner.hostname || "-" }}</dd>
              <dt>来源</dt>
              <dd>{{ runnerSourceLabel(selectedRunner.registration_source) }}</dd>
              <dt>归属组织</dt>
              <dd>{{ orgLabel(selectedRunner.org_id || "") || "未绑定" }}</dd>
              <dt>版本</dt>
              <dd class="mono">{{ selectedRunner.version || "-" }}</dd>
              <dt>最近心跳</dt>
              <dd>{{ runnerDetailHeartbeatLabel(selectedRunner, runnerPresenceContext(selectedRunner)) }}</dd>
              <dt>专属令牌</dt>
              <dd>{{ selectedRunner.has_token ? "已授权" : "未签发" }}</dd>
              <dt>能力</dt>
              <dd>
                <span v-for="cap in selectedRunner.capabilities" :key="cap" class="cap-tag">{{ cap }}</span>
                <span v-if="!selectedRunner.capabilities || !selectedRunner.capabilities.length">-</span>
              </dd>
            </dl>
            <p v-if="!isManagedRow(selectedRunner)" class="detail-empty remote-note">
              远程设备机：网页不能替你启动。请在插手机的那台电脑上执行启动命令，机房建议做成开机自启。
            </p>

            <h4 class="detail-subtitle">挂载设备（{{ detailDevices.length }}）</h4>
            <p v-if="!detailDevices.length" class="detail-empty">
              {{
                selectedRunner.online
                  ? "该节点当前无在线设备。"
                  : isManagedRow(selectedRunner) && !managedRunning
                    ? "本机托管未运行；启动后设备会自动上报。"
                    : "节点未连接，无法获取其实时设备信息。"
              }}
            </p>
            <div v-else class="detail-device-list">
              <div v-for="d in pagedDetailDevices" :key="d.udid" class="detail-device-row">
                <div class="ddr-main">
                  <span class="platform-mini-badge" :class="d.platform.toLowerCase()">
                    {{ platformBadgeLabel(d.platform) }}
                  </span>
                  <span class="ddr-name">{{ displayName(d) }}</span>
                  <span v-if="d.busy" class="st busy">占用中</span>
                  <span v-else-if="d.admin_disabled" class="st maint">维护中</span>
                  <span v-else class="st free">空闲</span>
                </div>
                <div class="ddr-meta mono">
                  <span :title="d.udid">{{ d.udid }}</span>
                  <span v-if="d.os_version">· {{ d.os_version }}</span>
                  <span v-if="d.backends?.length">· {{ d.backends.join(", ") }}</span>
                </div>
              </div>
              <DataPager
                v-if="detailDevices.length > NESTED_DEVICE_PAGE_SIZE || detailDevicePage > 1"
                :total="detailDevices.length"
                :page="detailDevicePage"
                :page-size="detailDevicePageSize"
                @update:page="setDetailDevicePage"
                @update:page-size="setDetailDevicePageSize"
              />
            </div>
          </div>
        </aside>
      </div>
    </Teleport>

    <ApModal
      v-if="deviceManagerOpen"
      title="管理测试设备"
      description="默认只列出待注册设备。已注册的置灰保留在「已注册」里，不会再次提交；取消注册后后续心跳不会自动加回。"
      wide
      :close-on-backdrop="!deviceManagerSaving"
      :close-on-esc="!deviceManagerSaving"
      @close="deviceManagerOpen = false"
    >
      <div class="device-manager-toolbar">
        <button type="button" class="small" @click="toggleAllInventory">
          {{ inventorySelectAllLabel }}
        </button>
        <label class="toolbar-search inventory-search">
          <input
            v-model="inventoryQuery"
            type="search"
            placeholder="搜索编号 / 型号…"
            aria-label="搜索设备"
          />
        </label>
        <span class="muted">
          已选 {{ checkedUdids.length }} / {{ inventorySelectable.length }}
          <template v-if="checkedPendingUdids.length || checkedRegisteredUdids.length">
            （待注册 {{ checkedPendingUdids.length }} · 已注册 {{ checkedRegisteredUdids.length }}）
          </template>
          <template v-if="inventoryQuery.trim()">
            · 筛选 {{ filteredInventory.length }} / {{ deviceInventory?.devices.length || 0 }}
          </template>
        </span>
      </div>
      <div
        v-if="deviceInventory?.devices.length"
        class="filter-chips inventory-status-chips"
        role="tablist"
        aria-label="设备注册状态筛选"
      >
        <button
          type="button"
          role="tab"
          class="filter-chip"
          :class="{ active: inventoryStatusFilter === 'pending' }"
          :aria-selected="inventoryStatusFilter === 'pending'"
          @click="inventoryStatusFilter = 'pending'"
        >
          待注册
          <span class="chip-count">{{ pendingInventoryCount }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="filter-chip"
          :class="{ active: inventoryStatusFilter === 'registered' }"
          :aria-selected="inventoryStatusFilter === 'registered'"
          @click="inventoryStatusFilter = 'registered'"
        >
          已注册
          <span class="chip-count">{{ registeredInventoryCount }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="filter-chip"
          :class="{ active: inventoryStatusFilter === 'all' }"
          :aria-selected="inventoryStatusFilter === 'all'"
          @click="inventoryStatusFilter = 'all'"
        >
          全部
        </button>
      </div>
      <div class="device-org-box">
        <p v-if="boundDeviceOrgId" class="hint">
          将注册到组织 <strong>{{ orgLabel(boundDeviceOrgId) }}</strong>。设备进组织池，不绑某个项目。
        </p>
        <label v-else-if="needsOrgOnRegister" class="provision-field">
          <span>归属组织</span>
          <ApSelect
            v-model="registerOrgId"
            :options="orgOptions"
            placeholder="选择本机节点归属组织"
            aria-label="本机节点归属组织"
          />
          <small class="hint">本机节点尚未绑定组织。选定后随注册写入；设备不绑某个项目。</small>
        </label>
        <p v-else class="hint">该节点尚未绑定组织。注册后设备跟随节点，不绑某个项目。</p>
      </div>
      <template v-if="deviceInventory?.devices.length">
      <div v-if="filteredInventory.length" class="inventory-list">
        <div
          v-for="d in pagedInventory"
          :key="d.udid"
          class="inventory-row"
          :class="{
            unavailable: Boolean(d.rejection_reason),
            'inventory-row-registered': deviceIsRegistered(d),
          }"
        >
          <label class="inventory-row-head">
            <input
              type="checkbox"
              :checked="checkedUdids.includes(d.udid)"
              :disabled="Boolean(d.rejection_reason)"
              @change="toggleInventoryDevice(d.udid, ($event.target as HTMLInputElement).checked)"
            />
            <span class="platform-mini-badge" :class="d.platform.toLowerCase()">{{ platformBadgeLabel(d.platform) }}</span>
            <span class="inventory-main">
              <strong>{{ displayName(d) }}</strong>
              <small class="mono">{{ d.udid }}</small>
            </span>
            <span class="pill" :class="{ ok: deviceIsRegistered(d) }">
              {{ deviceIsRegistered(d) ? "已注册" : "未注册" }}
            </span>
          </label>
          <aside v-if="d.occupancy_kind" class="occupancy-card">
            <div class="occupancy-card-head">
              <span class="occupancy-kind">{{ occupancyKindLabel(d.occupancy_kind) }}</span>
              <strong>{{ d.occupancy_reason || "未填写名称或用途" }}</strong>
            </div>
            <dl class="occupancy-grid">
              <div>
                <dt>占用人</dt>
                <dd>{{ d.occupancy_username || "未知" }}</dd>
              </div>
              <div>
                <dt>开始时间</dt>
                <dd>{{ formatTime(d.occupancy_start_at) }}</dd>
              </div>
              <div>
                <dt>{{ d.occupancy_kind === "reservation" ? "预占到期" : "结束时间" }}</dt>
                <dd>{{ d.occupancy_end_at ? formatTime(d.occupancy_end_at) : "任务完成时" }}</dd>
              </div>
              <div>
                <dt>{{ d.occupancy_kind === "job" ? "任务名称" : "预占用途" }}</dt>
                <dd>{{ d.occupancy_reason || "-" }}</dd>
              </div>
              <div class="occupancy-reference">
                <dt>{{ d.occupancy_kind === "job" ? "任务 ID" : "预占 ID" }}</dt>
                <dd class="mono" :title="d.occupancy_reference">{{ d.occupancy_reference || "-" }}</dd>
              </div>
            </dl>
          </aside>
          <small v-if="d.rejection_reason" class="managed-error">{{ d.rejection_reason }}</small>
        </div>
      </div>
      <div v-else-if="inventoryQuery.trim()" class="detail-empty">无匹配设备，请调整搜索</div>
      <div v-else-if="inventoryStatusFilter === 'pending'" class="detail-empty">
        当前无待注册设备。若刚完成登记，可在「已注册」查看；需要取消时切换到该页勾选。
      </div>
      <div v-else-if="inventoryStatusFilter === 'registered'" class="detail-empty">尚无已注册设备。</div>
      <div v-else class="detail-empty">未发现可管理设备。</div>
      <DataPager
        v-if="filteredInventory.length > NESTED_DEVICE_PAGE_SIZE || inventoryPage > 1"
        :total="filteredInventory.length"
        :page="inventoryPage"
        :page-size="inventoryPageSize"
        :loading="deviceManagerSaving"
        @update:page="setInventoryPage"
        @update:page-size="setInventoryPageSize"
      />
      </template>
      <div v-else class="detail-empty">
        未发现已授权的 Android / iOS 设备。请检查 USB、adb 授权或 iOS 信任状态后重新扫描。
      </div>
      <p v-if="deviceActionResult" class="device-action-result">{{ deviceActionResult }}</p>
      <template #actions>
        <button type="button" class="small" :disabled="deviceManagerSaving" @click="deviceManagerOpen = false">
          关闭
        </button>
        <button
          type="button"
          class="danger small"
          :disabled="deviceManagerSaving || !checkedRegisteredUdids.length"
          :title="checkedRegisteredUdids.length ? '' : '请先在「已注册」或「全部」中勾选已登记设备'"
          @click="applyDeviceSelection('unregister')"
        >
          取消所选注册
        </button>
        <button
          type="button"
          class="primary small"
          :disabled="deviceManagerSaving || !checkedPendingUdids.length"
          :title="checkedPendingUdids.length ? '' : '请勾选待注册设备；已登记设备不会重复提交'"
          @click="applyDeviceSelection('register')"
        >
          {{ deviceManagerSaving ? "处理中…" : checkedPendingUdids.length ? `注册所选（${checkedPendingUdids.length}）` : "注册所选" }}
        </button>
      </template>
    </ApModal>

    <ApModal
      v-if="provisionOpen"
      title="创建远程执行节点"
      description="每台插手机的电脑一个节点。生成的命令请在那台电脑上执行，不要在运行 Platform 的服务器上执行。"
      wide
      :close-on-backdrop="!provisionSaving"
      @close="provisionOpen = false"
    >
      <label class="provision-field">
        <span>归属组织</span>
        <ApSelect
          v-model="provisionOrgId"
          :options="orgOptions"
          placeholder="选择节点归属组织"
          aria-label="远程节点归属组织"
        />
      </label>
      <p v-if="!orgOptions.length" class="hint">
        创建远程节点需要先有组织。
        <template v-if="caps.canCreateOrg">请到「组织 / 事业部」新建后再回来。</template>
        <template v-else>请联系平台管理员创建组织。</template>
      </p>
      <label class="provision-field">
        <span>节点 ID</span>
        <input v-model.trim="provisionRunnerId" data-autofocus maxlength="128" placeholder="例如 lab-shanghai-01" />
      </label>
      <p class="hint">
        节点 ID 建议 <code>lab-地点-机器</code>。提交后启动命令只显示一次，请复制到插手机的电脑执行。
        关窗口会掉线；机房请用系统服务开机自启。节点必须归属组织；之后注册设备仍不绑项目。
      </p>
      <p v-if="provisionError" class="ap-field-error" role="alert">{{ provisionError }}</p>
      <template #actions>
        <button type="button" class="small" :disabled="provisionSaving" @click="provisionOpen = false">取消</button>
        <button
          type="button"
          class="primary small"
          :disabled="provisionSaving || !provisionOrgId || !provisionRunnerId.trim()"
          @click="provisionRunner"
        >
          {{ provisionSaving ? "正在创建…" : "创建并生成命令" }}
        </button>
      </template>
    </ApModal>
  </section>
</template>

<style scoped>
.panel-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.panel-header-row h2 {
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.device-manager-toolbar,
.inventory-row-head {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.device-manager-toolbar {
  justify-content: space-between;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}

.inventory-search {
  flex: 1 1 10rem;
  min-width: 8rem;
}

.inventory-search input {
  width: 100%;
  min-width: 0;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface, var(--control-bg));
  color: inherit;
  font-size: 0.8rem;
}

.inventory-list {
  display: grid;
  max-height: min(52vh, 32rem);
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.inventory-row {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.8rem;
  border-bottom: 1px solid var(--line);
}

.inventory-row-head {
  min-width: 0;
  cursor: pointer;
}

.inventory-row:last-child {
  border-bottom: 0;
}

.inventory-row:hover {
  background: var(--surface-soft);
}

.inventory-row.unavailable {
  cursor: not-allowed;
  opacity: 0.68;
}

.inventory-row.unavailable .inventory-row-head {
  cursor: not-allowed;
}

.inventory-row-registered {
  opacity: 0.72;
  background: var(--surface-soft, rgba(0, 0, 0, 0.02));
}

.inventory-row-registered .inventory-row-head {
  cursor: pointer;
}

.inventory-status-chips {
  margin-bottom: 0.65rem;
}

.inventory-main {
  display: grid;
  min-width: 0;
  margin-right: auto;
}

.inventory-main strong,
.inventory-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inventory-main small,
.muted {
  color: var(--muted);
}

.occupancy-card {
  display: grid;
  gap: 0.65rem;
  margin-left: 2rem;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--warning-soft-border);
  border-radius: 7px;
  background: var(--warning-soft-bg);
}

.occupancy-card-head {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
}

.occupancy-card-head strong {
  overflow: hidden;
  color: var(--warning-soft-fg);
  font-size: 0.82rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.occupancy-kind {
  flex: 0 0 auto;
  padding: 0.16rem 0.42rem;
  border: 1px solid var(--warning-soft-border);
  border-radius: 999px;
  color: var(--warning-soft-fg);
  background: var(--surface);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.occupancy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  gap: 0.55rem 0.9rem;
  margin: 0;
}

.occupancy-grid > div {
  min-width: 0;
}

.occupancy-grid dt {
  margin-bottom: 0.12rem;
  color: var(--muted);
  font-size: 0.68rem;
}

.occupancy-grid dd {
  overflow: hidden;
  margin: 0;
  color: var(--text);
  font-size: 0.76rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.occupancy-reference {
  grid-column: 1 / -1;
}

.device-action-result {
  margin: 0.75rem 0 0;
  padding: 0.65rem 0.75rem;
  border-radius: 6px;
  background: var(--surface-soft);
  font-size: 0.78rem;
  line-height: 1.5;
}

.provision-field {
  display: grid;
  gap: 0.35rem;
  margin-bottom: 0.8rem;
}

.provision-field > span {
  font-size: 0.76rem;
  font-weight: 700;
}

.provision-field :deep(.ap-select) {
  width: 100%;
}

.provision-field :deep(.ap-select) {
  width: 100%;
}

.device-org-box {
  margin: 0 0 0.75rem;
}

.device-org-box .hint,
.provision-field .hint {
  margin: 0.35rem 0 0;
  color: var(--muted);
  font-size: 0.76rem;
  line-height: 1.45;
}

.onboarding-note {
  grid-column: 1 / -1;
  padding-top: 0.65rem;
  border-top: 1px solid var(--line);
}

.managed-box {
  margin: 0 0 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-soft, var(--control-bg));
}

.managed-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
  gap: 0.45rem 0.65rem;
  padding: 0.7rem 0.9rem;
  cursor: pointer;
  list-style: none;
}

.managed-summary-leading {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}

.managed-summary::-webkit-details-marker {
  display: none;
}

.managed-summary small {
  color: var(--muted);
  font-size: 0.74rem;
}

.managed-head {
  padding: 0 0.9rem 0.75rem;
  border-top: 1px solid var(--line);
}

.managed-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding-top: 0.55rem;
}

.managed-hint {
  margin: 0.55rem 0.9rem 0.75rem;
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.45;
}

.managed-hint code {
  font-size: 0.85em;
}

.managed-error {
  margin: 0.4rem 0.9rem 0.75rem;
  font-size: 0.8rem;
  color: var(--bad);
}

.managed-log {
  margin: 0.55rem 0.9rem 0.9rem;
  max-height: 12rem;
  overflow: auto;
  padding: 0.55rem 0.65rem;
  font-size: 0.72rem;
  line-height: 1.4;
  background: var(--control-bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}

.muted-chip {
  font-size: 0.72rem;
  color: var(--muted);
  background: var(--control-bg);
  border: 1px solid var(--line);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}

.source-pill,
.managed-pill {
  margin-left: 0.35rem;
  font-size: 0.68rem;
}

.remote-note {
  margin: 0 0 1rem;
}

.capabilities-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.cap-more {
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 650;
  padding: 0.1rem 0.15rem;
}

.runner-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.device-count-cell {
  text-align: center;
  font-weight: 600;
}

.cap-tag {
  font-size: 0.72rem;
  background-color: var(--control-bg);
  border: 1px solid var(--line);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  color: var(--muted);
}

.runner-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0.65rem 0 0.7rem;
}

.runner-table {
  table-layout: fixed;
}

.runner-table th:nth-child(1) { width: 27%; }
.runner-table th:nth-child(2) { width: 15%; }
.runner-table th:nth-child(3) { width: 8%; }
.runner-table th:nth-child(4) { width: 25%; }
.runner-table th:nth-child(5) { width: 10%; }
.runner-table th:nth-child(6) { width: 15%; }

.runner-identity {
  min-width: 0;
}

.runner-identity .linkish-id {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  font-family: var(--font-mono, monospace);
}

.runner-identity small {
  display: block;
  margin-top: 0.25rem;
  color: var(--muted);
  font-size: 0.72rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runner-state-cell {
  vertical-align: top;
}

.runner-state-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.32rem;
}

.last-seen {
  color: var(--muted);
  font-size: 0.72rem;
  white-space: nowrap;
}

.token-state {
  color: var(--muted);
  font-size: 0.74rem;
  white-space: nowrap;
}

.token-state.issued {
  color: var(--ok-soft-fg);
}

.actions-col {
  text-align: right;
}

.quiet-action,
.danger-link,
.maintenance-action {
  background: transparent;
  box-shadow: none;
}

.danger-link,
.maintenance-action {
  border-color: transparent;
  color: var(--muted);
}

.danger-link:hover,
.maintenance-action:hover {
  color: var(--bad);
  background: var(--danger-soft-bg);
}

.maintenance-action {
  appearance: none;
  padding: 0.35rem 0.45rem;
  font: inherit;
  font-size: 0.75rem;
  cursor: pointer;
  border-radius: var(--radius-sm, 4px);
}

.empty-guide {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.4rem;
  text-align: left;
  max-width: 42rem;
  width: 100%;
  margin: 0.5rem auto;
  min-width: 0;
  line-height: 1.5;
}

.runner-empty-panel {
  margin-top: 0.75rem;
  padding: 1rem 1.1rem;
  border: 1px dashed var(--line-soft);
  border-radius: var(--radius-lg, 8px);
  background: var(--surface-soft);
}
.empty-guide .hint {
  margin: 0;
  opacity: 0.9;
  font-size: 0.86rem;
  white-space: normal;
  overflow-wrap: break-word;
}
.empty-guide ul {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0.15rem 0 0;
  padding-left: 1.35rem;
}
.empty-guide li {
  display: list-item;
  white-space: normal;
}
.empty-guide code {
  font-size: 0.85em;
  word-break: break-all;
}

.linkish-id {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  text-decoration: underline;
}

/* 节点详情抽屉 */
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  justify-content: flex-end;
  z-index: 1000;
}

.drawer {
  width: min(480px, 92vw);
  height: 100%;
  background: var(--surface-elevated);
  border-left: 1px solid var(--line);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  animation: drawer-in 0.18s ease-out;
}

@keyframes drawer-in {
  from { transform: translateX(24px); opacity: 0.4; }
  to { transform: translateX(0); opacity: 1; }
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--line);
}

.drawer-head-main {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.drawer-title {
  margin: 0;
  font-size: 0.95rem;
  word-break: break-all;
}

.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  color: var(--muted);
  padding: 0.25rem 0.5rem;
}

.drawer-body {
  padding: 1.25rem;
  overflow: auto;
}

.detail-grid {
  display: grid;
  grid-template-columns: 5rem 1fr;
  gap: 0.5rem 1rem;
  margin: 0 0 1.25rem;
}

.detail-grid dt {
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 600;
}

.detail-grid dd {
  margin: 0;
  font-size: 0.82rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.detail-subtitle {
  margin: 0 0 0.6rem;
  font-size: 0.85rem;
  font-weight: 700;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.35rem;
}

.detail-empty {
  color: var(--muted);
  font-size: 0.82rem;
}

.detail-device-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.detail-device-row {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.5rem 0.6rem;
  background: var(--surface-soft, var(--control-bg));
}

.ddr-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ddr-name {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ddr-meta {
  margin-top: 0.3rem;
  font-size: 0.72rem;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.platform-mini-badge {
  display: inline-block;
  min-width: 2.2em;
  text-align: center;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  border: 1px solid var(--line);
}
.platform-mini-badge.android { color: var(--ok-soft-fg, #2e7d32); }
.platform-mini-badge.ios { color: var(--purple-soft-fg, #6a1b9a); }
.platform-mini-badge.web { color: var(--info-soft-fg, #1565c0); }
.platform-mini-badge.http { color: var(--accent-text, #6a1b9a); }

.st {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
}
.st.busy { color: var(--bad); background: var(--danger-soft-bg); }
.st.maint { color: var(--warning-soft-fg); background: var(--warning-soft-bg); }
.st.free { color: var(--ok-soft-fg); background: var(--ok-soft-bg); }

.panel.compact {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
}

.compact-title {
  margin: 0 !important;
  font-size: 0.95rem !important;
  font-weight: 700;
  color: var(--text);
}

.runner-filter-chips {
  margin: 0;
}

.chip-count {
  margin-left: 0.35rem;
  font-size: 0.68rem;
  font-weight: 700;
  opacity: 0.85;
}

.chip-count.muted {
  opacity: 0.65;
}

.heartbeat-cell {
  font-size: 0.75rem;
  color: var(--muted);
  white-space: nowrap;
}

@media (max-width: 980px) {
  .runner-table th:nth-child(4),
  .runner-table td:nth-child(4) {
    display: none;
  }

  .runner-table th:nth-child(1) { width: 34%; }
  .runner-table th:nth-child(2) { width: 20%; }
  .runner-table th:nth-child(3) { width: 10%; }
  .runner-table th:nth-child(5) { width: 14%; }
  .runner-table th:nth-child(6) { width: 22%; }
}

@media (max-width: 700px) {
  .panel-header-row,
  .runner-list-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    margin-left: 0;
  }

  .runner-table-wrap {
    overflow-x: auto;
  }

  .runner-table {
    min-width: 42rem;
  }
}

.linkish-inline {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  margin: 0 0.15rem;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}
</style>
