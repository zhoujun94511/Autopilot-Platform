<script setup lang="ts">
defineOptions({ name: "DashboardPanel" });
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import { useProjectsStore } from "../stores/projectsStore";
import { useShellStore } from "../stores/shellStore";
import { useCapabilities } from "../composables/useCapabilities";
import StatusPill from "./StatusPill.vue";
import AgentOpsCard from "./AgentOpsCard.vue";
import JobQualityCard from "./JobQualityCard.vue";
import DesignDomainStatsCard from "./design/DesignDomainStatsCard.vue";
import { platformBadgeLabel } from "../utils/deviceDisplay";

const auth = useAuthStore();
const exec = useExecStore();
const opsStore = useOpsStore();
const projectsStore = useProjectsStore();
const shell = useShellStore();
const { healthOk } = storeToRefs(auth);
const { runners: runnersRef, jobs: jobsRef, devices, deviceBoard } = storeToRefs(exec);
const { ops } = storeToRefs(opsStore);
const { filterProjectId } = storeToRefs(projectsStore);

const caps = useCapabilities();

function selectTab(tab: string) {
  shell.activeTab = tab;
}

/** admin 用 /ops/summary；operator 用 runners/jobs/deviceBoard 本地聚合 */
const summary = computed(() => {
  if (ops.value) {
    const runnersOnline = ops.value.runners_online;
    const runnersRegistered = ops.value.runners_total;
    const runnersOffline =
      ops.value.runners_offline ??
      Math.max(0, runnersRegistered - runnersOnline);
    return {
      runnersOnline,
      runnersOffline,
      runnersRegistered,
      devicesBusy: ops.value.devices_busy,
      devicesTotal: ops.value.devices_total,
      jobsByStatus: ops.value.jobs_by_status || {},
      source: "ops" as const,
    };
  }
  const runnersList = runnersRef.value || [];
  const jobsList = jobsRef.value || [];
  const board = deviceBoard.value?.summary;
  const jobsByStatus: Record<string, number> = {};
  for (const j of jobsList) {
    const st = j.status || "unknown";
    jobsByStatus[st] = (jobsByStatus[st] || 0) + 1;
  }
  const runnersOnline = runnersList.filter((r) => r.online).length;
  return {
    runnersOnline,
    runnersOffline: Math.max(0, runnersList.length - runnersOnline),
    runnersRegistered: runnersList.length,
    devicesBusy: board?.busy ?? 0,
    devicesTotal: board?.online ?? devices.value?.length ?? 0,
    jobsByStatus,
    source: "local" as const,
  };
});

const activeJobs = computed(() => {
  const m = summary.value.jobsByStatus;
  return (m.running || 0) + (m.claimed || 0);
});

const freeDevices = computed(() => {
  if (deviceBoard.value) return deviceBoard.value.summary.free;
  return Math.max(0, summary.value.devicesTotal - summary.value.devicesBusy);
});

const recentJobs = computed(() => (jobsRef.value || []).slice(0, 8));

const healthLabel = computed(() => {
  if (healthOk.value === true) return "正常";
  if (healthOk.value === false) return "异常";
  return "检测中…";
});

/** 仅展示有设备的平台，避免空集群刷一排 0 */
const platformStats = computed(() => {
  const by = deviceBoard.value?.summary?.by_platform;
  if (!by) return [] as Array<{ plat: string; free: number; total: number }>;
  return Object.entries(by)
    .filter(([, s]) => Number((s as { total?: number })?.total || 0) > 0)
    .map(([plat, s]) => {
      const row = s as { free?: number; total?: number };
      return {
        plat: String(plat),
        free: Number(row.free || 0),
        total: Number(row.total || 0),
      };
    });
});

/** ops/summary 会预填全部状态为 0；前端只展示非零 */
const jobStatusEntries = computed(() =>
  Object.entries(summary.value.jobsByStatus || {}).filter(([, v]) => Number(v) > 0),
);

const showDistribution = computed(
  () => platformStats.value.length > 0 || jobStatusEntries.value.length > 0,
);

const recentSucceeded = computed(() => Number(summary.value.jobsByStatus.succeeded || 0));
const recentFailed = computed(() => Number(summary.value.jobsByStatus.failed || 0));

function onRunnerMetricClick() {
  selectTab(caps.canViewCluster ? "devices" : "jobs");
}

type ActionAlert = {
  id: string;
  title: string;
  detail: string;
  severity: "warn" | "error";
  tab: string;
};

/**
 * 仅在有真实阻塞时出现；不展示「一切正常」空态。
 * 普通用户：失败任务 / 无 Runner / 无设备；admin 额外看健康检查。
 */
const actionAlerts = computed((): ActionAlert[] => {
  const items: ActionAlert[] = [];
  const manageInfra = caps.canManageInfra;
  const canOps = caps.canOps;
  if (canOps && healthOk.value === false) {
    items.push({
      id: "health",
      title: "平台健康检查异常",
      detail: "请到运维配置中心排查",
      severity: "error",
      tab: "ops",
    });
  }
  if (summary.value.runnersOnline === 0) {
    const offline = summary.value.runnersOffline;
    items.push({
      id: "no-runner",
      title: "当前没有可用执行节点",
      detail: manageInfra
        ? offline > 0
          ? `无在线节点；另有 ${offline} 个历史注册已离线，可在执行节点注销`
          : "请启动 Runner 或检查节点接入"
        : "暂时无法发起批跑，可联系管理员或稍后重试",
      severity: "error",
      tab: manageInfra ? "devices" : "jobs",
    });
  } else if (manageInfra && summary.value.runnersOffline > 0) {
    items.push({
      id: "runners-offline",
      title: `${summary.value.runnersOffline} 个 Runner 已离线`,
      detail: `当前 ${summary.value.runnersOnline} 个在线，可清理无用历史注册`,
      severity: "warn",
      tab: "devices",
    });
  }
  if (summary.value.runnersOnline > 0 && summary.value.devicesTotal === 0) {
    items.push({
      id: "no-device",
      title: "暂无在线设备",
      detail: manageInfra
        ? "Runner 已就绪，设备池为空"
        : "没有可用设备时无法执行用例，请联系管理员",
      severity: "warn",
      tab: manageInfra ? "devices" : "jobs",
    });
  }
  const failed = summary.value.jobsByStatus.failed || 0;
  if (failed > 0) {
    items.push({
      id: "jobs-failed",
      title: `${failed} 个失败任务`,
      detail: "可在批跑中查看日志或重试",
      severity: "error",
      tab: "jobs",
    });
  }
  return items.slice(0, 4);
});
</script>

<template>
  <div class="dashboard-container">
    <div class="metrics-grid">
      <div
        class="metric-card"
        :class="{ 'metric-card-click': true }"
        role="button"
        tabindex="0"
        @click="onRunnerMetricClick"
        @keyup.enter="onRunnerMetricClick"
      >
        <div class="card-icon runner-icon">
          <svg viewBox="0 0 24 24" width="26" height="26" stroke="currentColor" stroke-width="2" fill="none">
            <rect x="2" y="2" width="20" height="8" rx="2" />
            <rect x="2" y="14" width="20" height="8" rx="2" />
            <line x1="6" y1="6" x2="6.01" y2="6" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
            <line x1="6" y1="18" x2="6.01" y2="18" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-label">{{ caps.canManageInfra ? "执行节点（实时）" : "批跑服务" }}</div>
          <div class="card-value">
            <template v-if="caps.canManageInfra">
              <span class="highlight">{{ summary.runnersOnline }}</span>
              <span class="total">在线</span>
            </template>
            <template v-else>
              <span class="highlight" :class="{ 'text-muted': !summary.runnersOnline }">
                {{ summary.runnersOnline ? "可用" : "不可用" }}
              </span>
            </template>
          </div>
          <div class="card-footer">
            <span class="pill-badge" :class="summary.runnersOnline ? 'success' : 'warn'">
              {{
                summary.runnersOnline
                  ? caps.canManageInfra
                    ? "服务就绪"
                    : "可发起批跑"
                  : caps.canManageInfra
                    ? "无在线节点"
                    : "暂不可用"
              }}
            </span>
            <span v-if="caps.canManageInfra && summary.runnersOffline > 0" class="footer-subtext">
              {{ summary.runnersOffline }} 个历史注册已离线
            </span>
            <span v-else-if="!caps.canManageInfra && !summary.runnersOnline" class="footer-subtext">
              请联系管理员配置执行环境
            </span>
          </div>
        </div>
      </div>

      <div v-if="caps.canManageInfra" class="metric-card">
        <div class="card-icon device-icon">
          <svg viewBox="0 0 24 24" width="26" height="26" stroke="currentColor" stroke-width="2" fill="none">
            <rect x="5" y="2" width="14" height="20" rx="2" />
            <line x1="12" y1="18" x2="12.01" y2="18" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-label">设备</div>
          <template v-if="summary.devicesTotal > 0">
            <div class="card-value">
              <span class="highlight">{{ summary.devicesBusy }}</span>
              <span class="total">占用 / 共 {{ summary.devicesTotal }}</span>
            </div>
            <div class="card-footer">
              <div class="progress-bar-container">
                <div
                  class="progress-bar"
                  :style="{ width: (summary.devicesBusy / summary.devicesTotal) * 100 + '%' }"
                ></div>
              </div>
              <span class="footer-subtext">空闲 {{ freeDevices }} 台</span>
            </div>
          </template>
          <template v-else>
            <div class="card-value">
              <span class="highlight">0</span>
              <span class="total">暂无在线设备</span>
            </div>
            <div class="card-footer">
              <span class="footer-subtext">接入设备后显示占用与空闲</span>
            </div>
          </template>
        </div>
      </div>

      <div class="metric-card">
        <div class="card-icon job-icon">
          <svg viewBox="0 0 24 24" width="26" height="26" stroke="currentColor" stroke-width="2" fill="none">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-label">进行中</div>
          <div class="card-value">
            <span class="highlight text-accent">{{ activeJobs }}</span>
            <span class="total">个活跃任务</span>
          </div>
          <div class="card-footer">
            <span class="footer-subtext">
              <template v-if="recentSucceeded || recentFailed">
                近期 {{ recentSucceeded }} 成功 / {{ recentFailed }} 失败
              </template>
              <template v-else>暂无近期完成记录</template>
              <template v-if="caps.canManageInfra && summary.source === 'local'">（本页列表）</template>
            </span>
          </div>
        </div>
      </div>

      <div v-if="caps.canOps" class="metric-card">
        <div class="card-icon" :class="healthOk ? 'health-icon-ok' : 'health-icon'">
          <svg viewBox="0 0 24 24" width="26" height="26" stroke="currentColor" stroke-width="2" fill="none">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-label">平台健康</div>
          <div class="card-value">
            <span
              class="highlight"
              :class="healthOk ? 'text-success' : healthOk === false ? 'text-error' : ''"
            >
              {{ healthLabel }}
            </span>
          </div>
          <div class="card-footer">
            <span class="footer-subtext">运维健康检查</span>
          </div>
        </div>
      </div>
    </div>

    <ul v-if="actionAlerts.length" class="alert-strip" aria-label="需要关注">
      <li
        v-for="t in actionAlerts"
        :key="t.id"
        class="alert-strip-item"
        :class="t.severity"
        @click="selectTab(t.tab)"
      >
        <div class="todo-text">
          <span class="todo-title">{{ t.title }}</span>
          <span class="todo-detail">{{ t.detail }}</span>
        </div>
        <span class="todo-go">→</span>
      </li>
    </ul>

    <DesignDomainStatsCard
      class="dashboard-panel"
      :project-id="filterProjectId || undefined"
      @goto-tab="selectTab"
    />

    <AgentOpsCard
      v-if="caps.canManageInfra || filterProjectId"
      class="dashboard-panel"
      :project-id="filterProjectId || undefined"
      @goto-tab="selectTab"
    />

    <JobQualityCard
      v-if="caps.canManageInfra || filterProjectId"
      class="dashboard-panel"
      :project-id="filterProjectId || undefined"
      @goto-tab="selectTab"
    />

    <div class="dashboard-dual">
      <div class="dashboard-panel panel">
        <div class="panel-head-row">
          <h3>近期批跑</h3>
          <div class="head-actions">
            <button type="button" class="small primary" @click="selectTab('jobs')">新建批跑</button>
            <button type="button" class="ghost small" @click="selectTab('jobs')">全部任务</button>
          </div>
        </div>
        <div v-if="!recentJobs.length" class="empty-state compact">
          <span>暂无任务记录</span>
        </div>
        <ul v-else class="recent-job-list">
          <li v-for="j in recentJobs" :key="j.id" class="recent-job-item">
            <div class="recent-job-main">
              <span class="recent-job-name" :title="j.name">{{ j.name || j.id.slice(0, 8) }}</span>
              <span class="recent-job-meta mono">{{ j.id.slice(0, 8) }}… · {{ j.platform }}</span>
            </div>
            <StatusPill :status="j.status" />
            <button
              type="button"
              class="small"
              title="查看日志"
              @click="exec.onViewJobLog(j.id)"
            >
              日志
            </button>
          </li>
        </ul>
        <nav class="dash-quick-row" aria-label="常用入口">
          <button type="button" class="linkish" @click="selectTab('app-builds')">应用资源</button>
          <span class="dash-quick-sep" aria-hidden="true">·</span>
          <button type="button" class="linkish" @click="selectTab('artifacts')">工程制品</button>
          <span class="dash-quick-sep" aria-hidden="true">·</span>
          <button type="button" class="linkish" @click="selectTab('reports')">测试报告</button>
          <span class="dash-quick-sep" aria-hidden="true">·</span>
          <button type="button" class="linkish" @click="selectTab('schedules')">定时计划</button>
        </nav>
      </div>
    </div>

    <div v-if="showDistribution" class="dashboard-sections">
      <div v-if="platformStats.length" class="dashboard-panel panel">
        <h3>设备分布</h3>
        <div class="platform-stats-wrapper">
          <div class="platform-list">
            <div class="platform-item" v-for="s in platformStats" :key="s.plat">
              <div class="platform-header">
                <span class="platform-name">{{ platformBadgeLabel(s.plat) }}</span>
                <span class="platform-ratio">{{ s.free }} 空闲 / {{ s.total }} 总台</span>
              </div>
              <div class="progress-bar-container">
                <div
                  class="progress-bar"
                  :class="s.plat.toLowerCase()"
                  :style="{
                    width: (s.total ? ((s.total - s.free) / s.total) * 100 : 0) + '%',
                  }"
                ></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="jobStatusEntries.length" class="dashboard-panel panel">
        <h3>任务队列分布</h3>
        <div class="status-summary-list">
          <div
            class="status-summary-item"
            v-for="[key, val] in jobStatusEntries"
            :key="key"
          >
            <StatusPill :status="String(key)" />
            <div class="status-count-row">
              <span class="status-count">{{ val }}</span>
              <span class="status-unit">个任务</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  width: 100%;
  max-width: none;
  min-width: 0;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
}

.metric-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 0.9rem 1rem 0.85rem;
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  box-shadow: none;
  border-left: 3px solid var(--line);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.metric-card:hover {
  transform: none;
  border-color: var(--accent);
  background: var(--surface-secondary);
}

.card-icon {
  display: none;
}

.metric-card-click {
  cursor: pointer;
}

.metric-card-click:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.card-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.runner-icon {
  background: var(--info-soft-bg);
  color: var(--accent-text);
}

.device-icon {
  background: var(--warning-soft-bg);
  color: var(--warning-soft-fg);
}

.job-icon {
  background: var(--ok-soft-bg);
  color: var(--ok-soft-fg);
}

.health-icon {
  background: var(--danger-soft-bg);
  color: var(--danger-soft-fg);
}

.health-icon-ok {
  background: var(--ok-soft-bg);
  color: var(--ok-soft-fg);
}

.card-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.card-label {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: none;
  letter-spacing: 0;
  margin-bottom: 0.15rem;
  font-weight: 600;
}

.card-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
  margin-bottom: 0.35rem;
}

.card-value .highlight {
  font-size: 1.75rem;
}

.card-value .total {
  font-size: 0.9rem;
  font-weight: 400;
  color: var(--muted);
  margin-left: 0.4rem;
}

.card-footer {
  margin-top: 0.25rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.3rem;
}

.pill-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  border-radius: 99px;
  font-weight: 500;
}

.pill-badge.success {
  background: var(--ok-soft-bg);
  color: var(--ok-soft-fg);
}

.pill-badge.warn {
  background: var(--danger-soft-bg);
  color: var(--danger-soft-fg);
}

.progress-bar-container {
  height: 6px;
  background: var(--track-bg);
  border-radius: 3px;
  overflow: hidden;
  margin: 0.4rem 0;
  width: 100%;
}

.progress-bar {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
}

.progress-bar.android {
  background: var(--ok);
}

.progress-bar.ios {
  background: var(--purple-soft-fg);
}

.footer-subtext {
  font-size: 0.75rem;
  color: var(--muted);
}

.dashboard-dual {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1rem;
  width: 100%;
}

.dashboard-sections {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
}

.dash-quick-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.15rem;
  margin-top: 0.85rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--line-soft);
  font-size: 0.8rem;
}

.dash-quick-sep {
  color: var(--muted);
  padding: 0 0.25rem;
}

.metric-card:has(.runner-icon) {
  border-left-color: var(--accent);
}

.metric-card:has(.device-icon) {
  border-left-color: var(--warning);
}

.metric-card:has(.job-icon) {
  border-left-color: var(--ok);
}

.metric-card:has(.health-icon-ok) {
  border-left-color: var(--ok);
}

.metric-card:has(.health-icon) {
  border-left-color: var(--bad);
}

.dashboard-panel {
  display: flex;
  flex-direction: column;
}

.panel-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}

.dashboard-panel h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}

.alert-strip {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.alert-strip-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  cursor: pointer;
  border-left-width: 3px;
  transition: var(--transition);
}

.alert-strip-item:hover {
  border-color: var(--accent);
}

.alert-strip-item.warn {
  border-left-color: var(--warning);
}

.alert-strip-item.error {
  border-left-color: var(--bad);
}

.recent-job-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.recent-job-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 0.55rem;
  align-items: center;
  padding: 0.65rem 0.75rem;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
}

.recent-job-main {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.recent-job-name {
  font-weight: 600;
  font-size: 0.88rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-job-meta {
  font-size: 0.72rem;
  color: var(--muted);
}

.todo-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.todo-title {
  font-weight: 600;
  font-size: 0.88rem;
}

.todo-detail {
  font-size: 0.75rem;
  color: var(--muted);
}

.todo-go {
  color: var(--muted);
  font-weight: 700;
}

.platform-stats-wrapper {
  background: var(--surface-soft);
  border-radius: 8px;
  padding: 1rem;
}

.platform-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.platform-item {
  display: flex;
  flex-direction: column;
}

.platform-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  margin-bottom: 0.3rem;
}

.platform-name {
  font-weight: 600;
  color: var(--text);
}

.platform-ratio {
  color: var(--muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 120px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--muted);
  font-size: 0.85rem;
}

.empty-state.compact {
  height: auto;
  min-height: 72px;
  padding: 1rem;
}

.status-summary-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  background: var(--surface-soft);
  border-radius: 8px;
  padding: 1rem;
}

.status-summary-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--line);
}

.status-summary-item:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.status-count-row {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
}

.status-count {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text);
}

.status-unit {
  font-size: 0.75rem;
  color: var(--muted);
}

.text-accent {
  color: var(--accent-text);
}

.text-muted {
  color: var(--muted);
  font-size: 1.35rem;
}

.text-success {
  color: var(--ok);
}

.text-error {
  color: var(--bad);
}

@media (max-width: 720px) {
  .recent-job-item {
    grid-template-columns: 1fr auto;
  }
  .recent-job-item .small {
    grid-column: 2;
    grid-row: 1;
  }
}
</style>
