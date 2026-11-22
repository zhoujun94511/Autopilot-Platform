<script setup lang="ts">
defineOptions({ name: "DashboardPanel" });
import { computed, defineAsyncComponent, onActivated, onDeactivated, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import {
  Activity,
  Server,
  Smartphone,
  ShieldCheck,
  AlertTriangle,
  Package,
  AppWindow,
  Clock,
  FileBarChart2,
  ListChecks,
  FileText,
  BookOpen,
  Play,
  ArrowRight,
} from "lucide-vue-next";
import type { Job } from "../api";
import { listJobsPage } from "../api/opsLists";
import { useAuthStore } from "../stores/auth";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import { useProjectsStore } from "../stores/projectsStore";
import { useShellStore } from "../stores/shellStore";
import { useCapabilities } from "../composables/useCapabilities";
import StatusPill from "./StatusPill.vue";
import JobLogViewer from "./JobLogViewer.vue";
import { goToHubSection } from "../navigation/tabSync";
import { platformBadgeLabel } from "../utils/deviceDisplay";
import { parseApiTime } from "../utils/parseApiTime";
import { JOB_STATUS_FILTERS } from "../utils/status";

const AgentOpsCard = defineAsyncComponent(() => import("./AgentOpsCard.vue"));
const JobQualityCard = defineAsyncComponent(() => import("./JobQualityCard.vue"));
const DesignDomainStatsCard = defineAsyncComponent(() => import("./design/DesignDomainStatsCard.vue"));

const auth = useAuthStore();
const exec = useExecStore();
const opsStore = useOpsStore();
const projectsStore = useProjectsStore();
const shell = useShellStore();
const router = useRouter();
const { healthOk, user } = storeToRefs(auth);
const { projects } = storeToRefs(projectsStore);
const {
  runners: runnersRef,
  runnersListVersion,
  jobs: jobsRef,
  jobsListVersion,
  jobsListTotal,
  devices,
  deviceBoard,
} = storeToRefs(exec);
const { ops } = storeToRefs(opsStore);
const { filterOrgId, filterProjectId } = storeToRefs(projectsStore);

const caps = useCapabilities();
const logJobId = ref<string | null>(null);
const overviewView = ref<"execution" | "analysis">("execution");
const analysisVisited = ref(false);
const waitingForJobs = ref(jobsListVersion.value === 0);
const dateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function createdAt(job: Job) {
  const time = parseApiTime(job.created_at);
  return Number.isFinite(time) ? dateTime.format(time) : "—";
}

function closeLog() {
  logJobId.value = null;
}

const statusTotals = ref<Record<string, number> | null>(null);
const statusReadFailed = ref(false);
const dashboardActive = ref(true);
let statusReadGeneration = 0;

onActivated(() => {
  dashboardActive.value = true;
});
onDeactivated(() => {
  closeLog();
  statusReadGeneration += 1;
  dashboardActive.value = false;
});
watch(
  [filterOrgId, filterProjectId],
  () => {
    waitingForJobs.value = true;
    statusReadGeneration += 1;
    statusTotals.value = null;
    statusReadFailed.value = false;
    closeLog();
  },
  { flush: "sync" },
);
watch(
  jobsListVersion,
  () => {
    waitingForJobs.value = false;
  },
  { flush: "sync" },
);

function selectTab(tab: string) {
  shell.activeTab = tab;
}

function openAnalysis() {
  analysisVisited.value = true;
  overviewView.value = "analysis";
}

const visibleJobs = computed(() => {
  if (waitingForJobs.value) return [];
  const projectId = filterProjectId.value.trim();
  return projectId
    ? jobsRef.value.filter((job) => job.project_id === projectId)
    : jobsRef.value;
});

const workspaceStatusTotals = computed(() =>
  !filterProjectId.value && !filterOrgId.value ? ops.value?.jobs_by_status : undefined,
);
const needsStatusTotals = computed(() =>
  !workspaceStatusTotals.value && jobsListTotal.value > visibleJobs.value.length,
);

watch(
  [jobsListVersion, needsStatusTotals, dashboardActive],
  async () => {
    const generation = ++statusReadGeneration;
    if (!dashboardActive.value || waitingForJobs.value || !needsStatusTotals.value) return;
    const projectId = filterProjectId.value.trim() || undefined;
    statusReadFailed.value = false;
    try {
      const statuses = JOB_STATUS_FILTERS.filter(({ value }) => value);
      const counts = await Promise.all(
        statuses.map(
          async ({ value }) =>
            [value, (await listJobsPage({ projectId, status: value, pageSize: 1 })).total] as const,
        ),
      );
      if (generation === statusReadGeneration) statusTotals.value = Object.fromEntries(counts);
    } catch {
      if (generation === statusReadGeneration) statusReadFailed.value = true;
    }
  },
  { immediate: true },
);

const jobsByStatus = computed(() => {
  if (waitingForJobs.value) return null;
  if (workspaceStatusTotals.value) return workspaceStatusTotals.value;
  if (needsStatusTotals.value) return statusTotals.value;
  const map: Record<string, number> = {};
  for (const job of visibleJobs.value) {
    const status = job.status || "unknown";
    map[status] = (map[status] || 0) + 1;
  }
  return map;
});

const summary = computed(() => {
  if (ops.value) {
    const runnersOnline = ops.value.runners_online;
    const runnersRegistered = ops.value.runners_total;
    const runnersOffline =
      ops.value.runners_offline ?? Math.max(0, runnersRegistered - runnersOnline);
    return {
      runnersOnline,
      runnersOffline,
      runnersRegistered,
      devicesBusy: ops.value.devices_busy,
      devicesTotal: ops.value.devices_total,
    };
  }
  const runnersList = runnersRef.value || [];
  const board = deviceBoard.value?.summary;
  const runnersOnline = runnersList.filter((r) => r.online).length;
  return {
    runnersOnline,
    runnersOffline: Math.max(0, runnersList.length - runnersOnline),
    runnersRegistered: runnersList.length,
    devicesBusy: board?.busy ?? 0,
    devicesTotal: board?.online ?? devices.value?.length ?? 0,
  };
});

const activeJobs = computed(() => {
  const m = jobsByStatus.value;
  if (!m) return "—";
  return (m.running || 0) + (m.claimed || 0);
});

const jobLoadLabel = computed(() =>
  shell.error ? "暂无法读取批跑任务" : "正在读取批跑任务…",
);

const queueLabel = computed(() => {
  if (waitingForJobs.value) return jobLoadLabel.value;
  if (statusReadFailed.value) return jobsByStatus.value ? "统计更新失败" : "无法读取任务统计";
  if (!jobsByStatus.value) return "正在读取任务统计…";
  return `${jobsByStatus.value.pending || 0} 个排队中`;
});

const freeDevices = computed(() => {
  if (deviceBoard.value) return deviceBoard.value.summary.free;
  return Math.max(0, summary.value.devicesTotal - summary.value.devicesBusy);
});

const recentJobs = computed(() => visibleJobs.value.slice(0, 8));

const healthLabel = computed(() => {
  if (healthOk.value === true) return "正常";
  if (healthOk.value === false) return "异常";
  return "待检测";
});

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

const jobStatusEntries = computed(() =>
  Object.entries(jobsByStatus.value || {}).filter(([, v]) => Number(v) > 0),
);

const runnersReady = computed(() => Boolean(ops.value) || runnersListVersion.value > 0);
const devicesReady = computed(() => Boolean(ops.value || deviceBoard.value));
const runnerStatus = computed(() => {
  if (!runnersReady.value) return "—";
  if (caps.canManageInfra) return summary.value.runnersOnline;
  return summary.value.runnersOnline > 0 ? "可用" : "不可用";
});

function openRunners() {
  if (caps.canViewCluster) goToHubSection(router, "devices", "runners");
  else selectTab("jobs");
}

type ActionAlert = {
  id: string;
  title: string;
  detail: string;
  severity: "warn" | "error";
  target: "jobs" | "devices" | "runners" | "ops";
};

function openAlert(alert: ActionAlert) {
  if (alert.id === "jobs-failed") void router.push({ path: "/exec/jobs", query: { status: "failed" } });
  else if (alert.target === "runners") openRunners();
  else selectTab(alert.target);
}

const actionAlerts = computed((): ActionAlert[] => {
  const items: ActionAlert[] = [];
  const manageInfra = caps.canManageInfra;
  const canOps = caps.canOps;
  if (canOps && healthOk.value === false) {
    items.push({
      id: "health",
      title: "平台健康检查异常",
      detail: "查看运维检查",
      severity: "error",
      target: "ops",
    });
  }
  if (runnersReady.value && summary.value.runnersOnline === 0) {
    const offline = summary.value.runnersOffline;
    items.push({
      id: "no-runner",
      title: "没有在线执行节点",
      detail: manageInfra
        ? offline > 0
          ? `${offline} 个节点已离线`
          : "查看节点配置"
        : "请联系管理员",
      severity: "error",
      target: manageInfra ? "runners" : "jobs",
    });
  } else if (manageInfra && summary.value.runnersOffline > 0) {
    items.push({
      id: "runners-offline",
      title: `${summary.value.runnersOffline} 个执行节点已离线`,
      detail: `${summary.value.runnersOnline} 个在线`,
      severity: "warn",
      target: "runners",
    });
  }
  if (devicesReady.value && summary.value.runnersOnline > 0 && summary.value.devicesTotal === 0) {
    items.push({
      id: "no-device",
      title: "暂无在线设备",
      detail: manageInfra ? "查看设备" : "请联系管理员",
      severity: "warn",
      target: manageInfra ? "devices" : "jobs",
    });
  }
  const failed = jobsByStatus.value?.failed || 0;
  if (failed > 0) {
    items.push({
      id: "jobs-failed",
      title: `${failed} 个失败任务`,
      detail: "查看失败任务",
      severity: "error",
      target: "jobs",
    });
  }
  return items.slice(0, 4);
});
const currentScopeLabel = computed(() => {
  const pid = filterProjectId.value.trim();
  if (pid) {
    const found = projects.value.find((p) => p.id === pid);
    return found ? `当前项目：${found.name}` : `当前项目：${pid}`;
  }
  return "当前范围：全部可见项目";
});
</script>

<template>
  <div class="vben-page overview">
    <!-- Workspace Welcome Banner (Vben Workspace Style) -->
    <section class="vben-card vben-welcome-banner" aria-label="工作台欢迎信息">
      <div class="vben-welcome-left">
        <span class="vben-welcome-avatar" aria-hidden="true">
          {{ (user?.username || "U").slice(0, 2).toUpperCase() }}
        </span>
        <div class="vben-welcome-copy">
          <h2 class="vben-welcome-title">欢迎使用工作台，{{ user?.username || "成员" }}</h2>
          <p class="vben-welcome-sub">
            {{ currentScopeLabel }} · 共 {{ summary.runnersOnline }} 个在线执行节点，{{ devicesReady ? freeDevices : 0 }} 台空闲设备
          </p>
        </div>
      </div>
      <div class="vben-welcome-actions">
        <button type="button" class="ghost" @click="selectTab('devices')">查看设备</button>
        <button type="button" class="primary" @click="selectTab('jobs')">前往批跑</button>
      </div>
    </section>

    <!-- Row 1: Vben v5 4-Column KPI Cards -->
    <section class="vben-kpi-grid" aria-label="运行状态">
      <button type="button" class="vben-kpi-card" @click="selectTab('jobs')">
        <div class="vben-kpi-top">
          <span class="vben-kpi-label">进行中任务</span>
          <span class="vben-kpi-icon blue" aria-hidden="true"><Activity :size="18" /></span>
        </div>
        <strong class="vben-kpi-value">{{ activeJobs }}</strong>
        <div class="vben-kpi-footer">
          <span>{{ queueLabel }}</span>
          <ArrowRight :size="13" aria-hidden="true" />
        </div>
      </button>

      <button type="button" class="vben-kpi-card" @click="openRunners">
        <div class="vben-kpi-top">
          <span class="vben-kpi-label">在线执行节点</span>
          <span class="vben-kpi-icon" :class="runnersReady && !summary.runnersOnline ? 'amber' : 'green'" aria-hidden="true">
            <Server :size="18" />
          </span>
        </div>
        <strong class="vben-kpi-value" :class="{ warn: runnersReady && !summary.runnersOnline }">
          {{ runnerStatus }}
        </strong>
        <div class="vben-kpi-footer">
          <span v-if="caps.canManageInfra && runnersReady">在线 / 共 {{ summary.runnersRegistered }} 个</span>
          <span v-else>查看执行节点</span>
          <ArrowRight :size="13" aria-hidden="true" />
        </div>
      </button>

      <button v-if="caps.canManageInfra" type="button" class="vben-kpi-card" @click="selectTab('devices')">
        <div class="vben-kpi-top">
          <span class="vben-kpi-label">可用设备</span>
          <span class="vben-kpi-icon indigo" aria-hidden="true"><Smartphone :size="18" /></span>
        </div>
        <strong class="vben-kpi-value">{{ devicesReady ? freeDevices : "—" }}</strong>
        <div class="vben-kpi-footer">
          <span v-if="devicesReady">{{ summary.devicesBusy }} 台占用 / {{ summary.devicesTotal }} 台在线</span>
          <span v-else>查看在线设备</span>
          <ArrowRight :size="13" aria-hidden="true" />
        </div>
      </button>

      <button v-if="caps.canOps" type="button" class="vben-kpi-card" @click="selectTab('ops')">
        <div class="vben-kpi-top">
          <span class="vben-kpi-label">平台健康</span>
          <span class="vben-kpi-icon" :class="healthOk === false ? 'red' : 'green'" aria-hidden="true">
            <ShieldCheck :size="18" />
          </span>
        </div>
        <strong class="vben-kpi-value" :class="{ bad: healthOk === false }">{{ healthLabel }}</strong>
        <div class="vben-kpi-footer">
          <span>查看运维检查与配置</span>
          <ArrowRight :size="13" aria-hidden="true" />
        </div>
      </button>
    </section>

    <!-- Row 2: View Switcher -->
    <div class="vben-view-bar">
      <div class="vben-segmented" role="tablist" aria-label="总览视图">
        <button
          type="button"
          role="tab"
          :aria-selected="overviewView === 'execution'"
          aria-controls="overview-execution"
          :class="{ 'is-active': overviewView === 'execution' }"
          @click="overviewView = 'execution'"
        >
          工作台 · 近期执行
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="overviewView === 'analysis'"
          aria-controls="overview-analysis"
          :class="{ 'is-active': overviewView === 'analysis' }"
          @click="openAnalysis"
        >
          运行分析
        </button>
      </div>
    </div>

    <!-- Workspace View: 2-Column Asymmetric Grid -->
    <section
      v-show="overviewView === 'execution'"
      id="overview-execution"
      class="vben-workspace-grid"
      aria-labelledby="overview-jobs"
    >
      <div class="vben-workspace-main">
        <div v-if="actionAlerts.length" class="vben-card">
          <div class="vben-card-header">
            <h3 class="vben-card-title">待处理告警</h3>
            <span class="vben-count-pill warn">{{ actionAlerts.length }} 项</span>
          </div>
          <ul class="vben-alert-list">
            <li v-for="alert in actionAlerts" :key="alert.id" :class="alert.severity">
              <button type="button" class="vben-alert-row" @click="openAlert(alert)">
                <span class="vben-alert-icon" aria-hidden="true"><AlertTriangle :size="15" /></span>
                <strong class="vben-alert-title">{{ alert.title }}</strong>
                <span v-if="alert.detail" class="vben-alert-detail">{{ alert.detail }}</span>
                <ArrowRight :size="14" class="vben-alert-arrow" aria-hidden="true" />
              </button>
            </li>
          </ul>
        </div>

        <div class="vben-card">
          <div class="vben-card-header">
            <h3 id="overview-jobs" class="vben-card-title">近期批跑</h3>
            <button type="button" class="vben-link-btn" @click="selectTab('jobs')">
              全部任务 <ArrowRight :size="13" aria-hidden="true" />
            </button>
          </div>
          <div class="table-wrap vben-table-flush">
            <table aria-labelledby="overview-jobs">
              <thead>
                <tr>
                  <th scope="col">任务名称</th>
                  <th scope="col">平台</th>
                  <th scope="col">状态</th>
                  <th scope="col">创建时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!recentJobs.length">
                  <td class="vben-empty-cell" colspan="5">
                    <div class="vben-empty-box">
                      <span>{{ waitingForJobs ? jobLoadLabel : "暂无批跑任务" }}</span>
                      <button v-if="!waitingForJobs" type="button" class="vben-empty-cta" @click="selectTab('jobs')">
                        前往批跑列表
                      </button>
                    </div>
                  </td>
                </tr>
                <tr v-for="job in recentJobs" :key="job.id">
                  <td class="job-name" :title="job.name || job.id">{{ job.name || job.id.slice(0, 8) }}</td>
                  <td>
                    <span class="vben-plat-tag">{{ platformBadgeLabel(job.platform) }}</span>
                  </td>
                  <td><StatusPill :status="job.status" /></td>
                  <td class="job-date">{{ createdAt(job) }}</td>
                  <td>
                    <button
                      type="button"
                      class="vben-link-btn"
                      :aria-label="'查看 ' + (job.name || job.id) + ' 的日志'"
                      @click="logJobId = job.id"
                    >
                      日志
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <aside class="vben-workspace-side">
        <div class="vben-card">
          <div class="vben-card-header">
            <h3 class="vben-card-title">快捷导航</h3>
          </div>
          <nav class="vben-quick-grid" aria-label="常用操作">
            <button type="button" class="vben-quick-tile" @click="selectTab('design-docs')">
              <span class="tile-icon blue"><FileText :size="20" /></span>
              <span>需求文档</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('design-cases')">
              <span class="tile-icon indigo"><ListChecks :size="20" /></span>
              <span>意图用例</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('design-knowledge')">
              <span class="tile-icon amber"><BookOpen :size="20" /></span>
              <span>知识库</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('jobs')">
              <span class="tile-icon indigo"><Play :size="20" /></span>
              <span>批跑任务</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('devices')">
              <span class="tile-icon green"><Smartphone :size="20" /></span>
              <span>在线设备</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('artifacts')">
              <span class="tile-icon amber"><Package :size="20" /></span>
              <span>工程制品</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('app-builds')">
              <span class="tile-icon blue"><AppWindow :size="20" /></span>
              <span>应用资源</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('schedules')">
              <span class="tile-icon indigo"><Clock :size="20" /></span>
              <span>定时计划</span>
            </button>
            <button type="button" class="vben-quick-tile" @click="selectTab('reports')">
              <span class="tile-icon green"><FileBarChart2 :size="20" /></span>
              <span>测试报告</span>
            </button>
          </nav>
        </div>

        <div class="vben-card">
          <div class="vben-card-header">
            <h3 class="vben-card-title">设备平台分布</h3>
            <button type="button" class="vben-link-btn" @click="selectTab('devices')">
              设备管理 <ArrowRight :size="13" aria-hidden="true" />
            </button>
          </div>
          <div class="vben-card-body">
            <div v-if="platformStats.length" class="vben-plat-bars">
              <div v-for="item in platformStats" :key="item.plat" class="vben-plat-row">
                <div class="vben-plat-meta">
                  <strong>{{ platformBadgeLabel(item.plat) }}</strong>
                  <span>{{ item.free }} 空闲 / {{ item.total }} 台在线</span>
                </div>
                <div class="vben-progress-track">
                  <div
                    class="vben-progress-fill"
                    :style="{ width: `${item.total ? Math.round((item.free / item.total) * 100) : 0}%` }"
                  ></div>
                </div>
              </div>
            </div>
            <p v-else class="vben-side-empty">暂无在线设备统计</p>
          </div>
        </div>
      </aside>
    </section>

    <!-- Analysis View -->
    <section
      v-show="overviewView === 'analysis'"
      id="overview-analysis"
      class="vben-analysis-grid"
      aria-label="运行分析"
    >
      <template v-if="analysisVisited">
        <div v-if="jobStatusEntries.length" class="vben-card">
          <div class="vben-card-header">
            <h3 class="vben-card-title">任务状态分布</h3>
          </div>
          <div class="vben-card-body">
            <ul class="vben-stat-list">
              <li v-for="[status, count] in jobStatusEntries" :key="status">
                <StatusPill :status="status" />
                <strong>{{ count }}</strong>
              </li>
            </ul>
          </div>
        </div>
        <DesignDomainStatsCard :project-id="filterProjectId || undefined" @goto-tab="selectTab" />
        <template v-if="caps.canManageInfra || filterProjectId">
          <JobQualityCard :project-id="filterProjectId || undefined" @goto-tab="selectTab" />
          <AgentOpsCard :project-id="filterProjectId || undefined" @goto-tab="selectTab" />
        </template>
      </template>
    </section>

    <JobLogViewer v-if="logJobId" :job-id="logJobId" @close="closeLog" />
  </div>
</template>

<style scoped>
.vben-welcome-banner {
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 14px;
}

.vben-welcome-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.vben-welcome-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(135deg, #006be6, #4f46e5);
  color: #ffffff;
  font-size: 15px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.vben-welcome-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.vben-welcome-title {
  margin: 0;
  font-size: var(--vben-fs-card-title, 18px);
  font-weight: 600;
  color: var(--vben-fg-strong);
  line-height: 1.35;
}

.vben-welcome-sub {
  margin: 0;
  font-size: var(--vben-fs-sm, 14px);
  color: var(--vben-fg-muted);
}

.vben-welcome-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.vben-view-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vben-segmented {
  display: inline-flex;
  align-items: center;
  padding: 3px;
  border-radius: 8px;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  box-shadow: var(--vben-shadow-card);
  gap: 2px;
}

.vben-segmented button {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--vben-fg-muted);
  font-size: 13px;
  font-weight: 500;
  padding: 5px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-segmented button:hover {
  color: var(--vben-fg-strong);
}

.vben-segmented button.is-active {
  background: var(--vben-primary);
  color: #ffffff;
  font-weight: 600;
}

.vben-workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

.vben-workspace-main,
.vben-workspace-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.vben-count-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}

.vben-count-pill.warn {
  background: var(--warning-soft-bg);
  color: var(--warning-soft-fg);
  border: 1px solid var(--warning-soft-border);
}

.vben-alert-list {
  list-style: none;
  margin: 0;
  padding: 8px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vben-alert-row {
  appearance: none;
  border: 1px solid var(--vben-border-soft);
  background: var(--vben-bg-muted);
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.vben-alert-row:hover {
  border-color: var(--vben-primary-border);
  background: var(--vben-bg-hover);
}

.vben-alert-list li.warn .vben-alert-icon {
  color: #f59e0b;
}
.vben-alert-list li.error .vben-alert-icon {
  color: #ef4444;
}

.vben-alert-title {
  font-size: var(--vben-fs-base, 14.5px);
  font-weight: 600;
  color: var(--vben-fg-strong);
}

.vben-alert-detail {
  font-size: var(--vben-fs-sm, 13.5px);
  color: var(--vben-fg-muted);
  margin-left: auto;
}

.vben-alert-arrow {
  color: var(--vben-fg-subtle);
  flex-shrink: 0;
}

.vben-link-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--vben-primary);
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  cursor: pointer;
  border-radius: 4px;
}

.vben-link-btn:hover {
  background: var(--vben-primary-soft);
}

.vben-table-flush {
  border: none;
  border-radius: 0 0 12px 12px;
  overflow-x: auto;
}

.vben-table-flush table tbody td.vben-empty-cell {
  text-align: center;
  padding: 40px 16px;
}

.vben-empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--vben-fg-muted);
  font-size: 13.5px;
}

.vben-empty-cta {
  appearance: none;
  border: 1px solid var(--vben-border);
  background: var(--vben-bg-surface);
  color: var(--vben-primary);
  padding: 5px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.vben-empty-cta:hover {
  border-color: var(--vben-primary);
  background: var(--vben-primary-soft);
}

.vben-plat-tag {
  display: inline-flex;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  background: var(--vben-bg-muted);
  color: var(--vben-fg);
}

.job-name {
  font-weight: 500;
  color: var(--vben-fg-strong);
}

.job-date {
  font-variant-numeric: tabular-nums;
  color: var(--vben-fg-muted);
  white-space: nowrap;
}

.vben-quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.vben-quick-tile {
  appearance: none;
  border: none;
  border-right: 1px solid var(--vben-border-soft);
  border-bottom: 1px solid var(--vben-border-soft);
  background: transparent;
  padding: 18px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--vben-fg);
  font-size: var(--vben-fs-sm, 14px);
  font-weight: 500;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.vben-quick-tile:nth-child(3n) {
  border-right: none;
}

.vben-quick-tile:hover {
  background: var(--vben-bg-hover);
  color: var(--vben-primary);
}

.tile-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.tile-icon.blue {
  background: rgba(0, 107, 230, 0.1);
  color: var(--vben-primary);
}
.tile-icon.indigo {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}
.tile-icon.green {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}
.tile-icon.amber {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.vben-plat-bars {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.vben-plat-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vben-plat-meta {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.vben-plat-meta strong {
  color: var(--vben-fg-strong);
  font-weight: 600;
}

.vben-plat-meta span {
  color: var(--vben-fg-muted);
  font-variant-numeric: tabular-nums;
}

.vben-progress-track {
  height: 7px;
  border-radius: 999px;
  background: var(--vben-bg-muted);
  overflow: hidden;
}

.vben-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #006be6, #38bdf8);
  transition: width 0.25s ease;
}

.vben-side-empty {
  margin: 0;
  text-align: center;
  padding: 20px 0;
  color: var(--vben-fg-muted);
  font-size: 13px;
}

.vben-analysis-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 16px;
}

.vben-stat-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.vben-stat-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--vben-border-soft);
}

.vben-stat-list li:last-child {
  border-bottom: none;
}

@media (max-width: 1080px) {
  .vben-workspace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
