<script setup lang="ts">
defineOptions({ name: "JobsPanel" });

import { computed, onDeactivated, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { Job } from "../api";
import { listJobsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { refreshScopes, registerJobsPage } from "../composables/mcPolling";
import { hasActiveJobs } from "../composables/mcRefreshScopes";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import { useAdminStore } from "../stores/adminStore";
import DataPager from "./common/DataPager.vue";
import ApModal from "./ApModal.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import JobCreatePanel from "./JobCreatePanel.vue";
import JobLogViewer from "./JobLogViewer.vue";
import StatusPill from "./StatusPill.vue";
import { JOB_STATUS_FILTERS } from "../utils/status";
import { platformBadgeLabel } from "../utils/deviceDisplay";
import { parseApiTime } from "../utils/parseApiTime";

const projectsStore = useProjectsStore();
const { filterProjectId, filterOrgId, projects } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const admin = useAdminStore();
const { jobMsg, jobMsgOk, logJobId, artifacts, submitting } = storeToRefs(exec);

const caps = useCapabilities();
const canCreateJob = computed(() => Boolean(caps.canEditProject));
const search = ref("");
const searchQuery = ref("");
const statusFilter = ref("");
const route = useRoute();
const router = useRouter();
const createOpen = ref(false);
const createPending = ref(false);
const createdMessage = ref("");
const filtered = computed(() => Boolean(statusFilter.value || searchQuery.value));
const projectNames = computed(() => new Map(projects.value.map((p) => [p.id, p.name])));
const artifactNames = computed(() => new Map(artifacts.value.map((a) => [a.id, a.name || a.filename])));
const dateTime = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hour12: false,
});

function createdAt(job: Job) {
  const time = parseApiTime(job.created_at);
  return Number.isFinite(time) ? dateTime.format(time) : "—";
}

function executionSource(job: Job) {
  if (!job.artifact_id) return job.project_dir || "—";
  return artifactNames.value.get(job.artifact_id) || `制品 ${job.artifact_id.slice(0, 8)}`;
}

function clearFilters() {
  search.value = "";
  searchQuery.value = "";
  setStatusFilter("");
}

function setStatusFilter(value: string) {
  const query = { ...route.query };
  if (value) query.status = value;
  else delete query.status;
  void router.push({ query });
}

watch(() => [route.meta.tab, route.query.status], ([tab, status]) => {
  if (tab === "jobs") {
    statusFilter.value = JOB_STATUS_FILTERS.find((filter) => filter.value === status)?.value ?? "";
  }
}, { immediate: true });

const list = usePagedList<Job>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listJobsPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
      q: searchQuery.value || undefined,
      status: statusFilter.value || undefined,
    }),
  resetSources: [filterOrgId, filterProjectId],
  filterSources: [statusFilter, searchQuery],
  // filterSources: [statusFilter] remains part of the empty-state contract.
  isUnfiltered: () => !statusFilter.value && !searchQuery.value,
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;
registerJobsPage({
  refresh: () => reload(false),
  hasActiveJobs: () => hasActiveJobs(items.value),
  isCreateOpen: () => createOpen.value,
});

watch(search, (value, _previous, onCleanup) => {
  const timer = setTimeout(() => { searchQuery.value = value.trim(); }, 280);
  onCleanup(() => clearTimeout(timer));
});

void reload(true);

function openCreate() {
  if (createPending.value || submitting.value) return;
  jobMsg.value = "";
  createdMessage.value = "";
  const pid = filterProjectId.value.trim();
  if (pid) exec.form.project_id = pid;
  createOpen.value = true;
  void refreshScopes(["devices", "artifacts", "app-builds", "projects"]);
}

function closeCreate() {
  if (createPending.value || submitting.value) return;
  createOpen.value = false;
}

function closeRowActions(event: Event) {
  const actions = (event.target as HTMLElement | null)?.closest<HTMLDetailsElement>(".job-row-menu");
  if (!actions?.open) return;
  actions.open = false;
  actions.querySelector("summary")?.focus();
}

function runRowAction(event: MouseEvent, action: () => unknown) {
  closeRowActions(event);
  void action();
}

onDeactivated(() => {
  createOpen.value = false;
  exec.closeJobLog();
});

watch([filterOrgId, filterProjectId], () => {
  createOpen.value = false;
  createdMessage.value = "";
  exec.closeJobLog();
});

watch(
  jobMsg,
  (m) => {
    if (
      createOpen.value &&
      jobMsgOk.value &&
      String(m || "").startsWith("已创建任务")
    ) {
      createdMessage.value = m;
      if (!m.includes("\n")) createOpen.value = false;
    }
  },
);
</script>

<template>
  <section class="jobs-panel" aria-labelledby="jobs-title">
    <header class="jobs-header">
      <h2 id="jobs-title">批跑</h2>
      <div class="page-hero-actions">
        <button type="button" class="ghost" :disabled="loading" @click="reload(false)">刷新</button>
        <button v-if="canCreateJob" type="button" class="primary" @click="openCreate">
          新建批跑
        </button>
      </div>
    </header>

    <div class="vben-card jobs-table-card">
      <div class="jobs-toolbar">
        <div class="filter-chips job-status-filters" role="group" aria-label="任务状态筛选">
          <button
            v-for="f in JOB_STATUS_FILTERS"
            :key="f.value || 'all'"
            type="button"
            :aria-pressed="statusFilter === f.value"
            @click="setStatusFilter(f.value)"
          >
            {{ f.label }}
          </button>
        </div>
        <div class="jobs-search">
          <label class="toolbar-search">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input id="jobs-search-input" v-model="search" name="jobs-search" type="search" aria-label="搜索批跑任务" placeholder="名称、ID 或节点" />
          </label>
        </div>
      </div>

      <ExecProjectGateBanner class="job-feedback" action-hint="新建批跑" />
      <div v-if="createdMessage" class="msg ok job-created job-feedback" role="status">{{ createdMessage }}</div>
      <div v-if="error" class="job-feedback list-error" role="alert">
        <span>{{ error }}</span>
        <button type="button" class="linkish" :disabled="loading" @click="reload(false)">重试</button>
      </div>

      <div class="table-wrap jobs-results" tabindex="0" role="region" aria-label="批跑列表" :aria-busy="loading">
      <table class="jobs-table" :class="{ 'has-jobs': items.length > 0 }" aria-label="批跑任务">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">状态</th>
            <th scope="col">执行目标</th>
            <th scope="col">创建时间</th>
            <th scope="col">工程来源</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && !error">
            <td class="empty" colspan="6">
              <div v-if="!items.length && hasLoaded" class="empty-stack">
                <template v-if="filtered">
                  <span>无匹配任务</span>
                  <button type="button" class="linkish" @click="clearFilters">清除筛选</button>
                </template>
                <span v-else>暂无批跑任务</span>
              </div>
              <span v-else role="status">正在加载批跑任务…</span>
            </td>
          </tr>
          <tr v-for="j in items" :key="j.id">
            <td>
              <strong class="job-title" :title="j.name">{{ j.name }}</strong>
              <button type="button" class="linkish job-id" :aria-label="'复制任务 ID ' + j.id" :title="j.id" @click="admin.copyText(j.id)">
                {{ j.id.length > 12 ? j.id.slice(0, 12) + "…" : j.id }}
              </button>
            </td>
            <td>
              <StatusPill :status="j.status" />
              <span v-if="j.status === 'failed' && j.error" class="job-meta job-failure" :title="j.error">{{ j.error }}</span>
            </td>
            <td>
              <span class="platform-mini-badge" :class="j.platform?.toLowerCase()">
                {{ platformBadgeLabel(j.platform) }}
              </span>
              <span v-if="j.runner_id" class="job-meta" :title="j.runner_id">{{ j.runner_id }}</span>
            </td>
            <td class="job-time" :title="j.created_at || undefined">{{ createdAt(j) }}</td>
            <td>
              <span class="job-title" :title="j.artifact_id || j.project_dir">{{ executionSource(j) }}</span>
              <span v-if="j.project_id && !filterProjectId" class="job-meta" :title="j.project_id">{{ projectNames.get(j.project_id) || j.project_id }}</span>
              <span v-if="j.app_build_id" class="job-meta" :title="j.app_build_id">
                {{ j.app_build_name || "应用" }}{{ j.app_version_name ? " v" + j.app_version_name : "" }}
              </span>
            </td>
            <td>
              <div class="actions-cell">
                <button
                  v-if="exec.canViewReport(j.status)"
                  type="button"
                  class="linkish"
                  title="查看测试报告"
                  @click="exec.onViewReport(j.id)"
                >
                  报告
                </button>
                <button type="button" class="linkish" title="查看日志" @click="exec.onViewJobLog(j.id)">
                  日志
                </button>
                <details
                  v-if="caps.canShareWrite || (!caps.isProjectViewer && (exec.canCancel(j.status) || exec.canRetry(j.status)))"
                  class="job-row-menu"
                  name="job-row-actions"
                  @keydown.esc.stop="closeRowActions"
                >
                  <summary :aria-label="`${j.name} 的更多操作`">更多</summary>
                  <div class="job-row-menu-actions">
                    <button
                      v-if="!caps.isProjectViewer && exec.canRetry(j.status)"
                      type="button"
                      class="linkish"
                      @click="runRowAction($event, () => exec.onRetryJob(j.id))"
                    >
                      重试
                    </button>
                    <button
                      v-if="caps.canShareWrite"
                      type="button"
                      class="linkish"
                      @click="runRowAction($event, () => ops.selectJobForShare(j.id))"
                    >
                      分享
                    </button>
                    <button
                      v-if="!caps.isProjectViewer && exec.canCancel(j.status)"
                      type="button"
                      class="linkish job-danger"
                      @click="runRowAction($event, () => exec.onCancelJob(j.id))"
                    >
                      取消任务
                    </button>
                  </div>
                </details>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <DataPager
      v-if="total > 0"
      class="jobs-pager"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />
    </div>

    <JobLogViewer
      v-if="logJobId"
      :job-id="logJobId"
      @close="exec.closeJobLog"
    />

    <ApModal
      v-if="createOpen"
      variant="drawer"
      title="新建批跑"
      :close-on-backdrop="false"
      :close-on-esc="!createPending && !submitting"
      @close="closeCreate"
    >
      <div class="job-create-scroll">
        <JobCreatePanel embedded @pending-change="createPending = $event" @cancel="closeCreate" />
      </div>
    </ApModal>
  </section>
</template>

<style scoped>
.jobs-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
  border: none;
  border-radius: 0;
}

.jobs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: 14px 20px;
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: var(--vben-radius-xl);
  box-shadow: var(--vben-shadow-card);
}

.jobs-table-card {
  overflow: hidden;
}

.jobs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: 0 20px;
  border-bottom: 1px solid var(--vben-border-soft);
}

.jobs-results {
  border: none;
  border-radius: 0;
}

.jobs-header h2 {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-title);
  font-weight: 650;
}

.jobs-toolbar {
  padding-block: 0;
}

.job-status-filters {
  gap: var(--space-3);
}

.job-status-filters button {
  padding: 0 6px;
  min-height: 47px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
}

.job-status-filters button:hover,
.job-status-filters button[aria-pressed="true"] {
  color: var(--accent-text);
}

.job-status-filters button[aria-pressed="true"] {
  border-bottom-color: var(--accent);
  font-weight: 650;
}

.jobs-search {
  padding-block: 6px;
}

.jobs-search .toolbar-search {
  min-width: 0;
  width: min(260px, 100%);
}

.jobs-search input {
  min-width: 0;
}

.jobs-results {
  margin: 0;
  border: 0;
  border-radius: 0;
}

.jobs-results:focus-visible {
  outline-offset: -2px;
}

.jobs-table.has-jobs {
  min-width: 790px;
}

.jobs-table th:first-child,
.jobs-table td:first-child {
  padding-inline-start: 20px;
}

.jobs-table th:last-child,
.jobs-table td:last-child {
  padding-inline-end: 20px;
}

.jobs-table td.empty {
  height: 148px;
  text-align: center;
}

.jobs-table .empty-stack {
  align-items: center;
  margin-inline: auto;
}

.jobs-pager {
  margin: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--line-soft);
}

.job-feedback {
  margin: var(--space-3) 20px;
}

.job-created {
  white-space: pre-wrap;
}

.list-error {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-3);
  color: var(--bad);
}

.jobs-table .job-title {
  display: block;
  max-width: 24rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jobs-table .job-id,
.jobs-table .job-meta {
  display: block;
  max-width: 22rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jobs-table .job-id {
  margin-top: 0.25rem;
  color: var(--muted);
  font-family: var(--mono);
  font-size: var(--font-size-meta);
  text-decoration: none;
  text-align: left;
}

.jobs-table .job-id:hover {
  color: var(--accent-text);
  text-decoration: underline;
}

.jobs-table .job-meta,
.jobs-table .job-time {
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.jobs-table .job-failure {
  margin-top: 0.25rem;
  color: var(--bad);
}

.platform-mini-badge {
  font-size: var(--font-size-meta);
  color: var(--muted);
}

.platform-mini-badge.http,
.platform-mini-badge.web {
  color: var(--text);
}

.job-danger {
  color: var(--bad);
}

.job-create-scroll {
  min-height: 0;
  overflow: auto;
  padding: 4px;
}

.actions-cell {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  white-space: nowrap;
}

.job-row-menu > summary {
  cursor: pointer;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.job-row-menu-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

@media (max-width: 720px) {
  .jobs-header,
  .jobs-toolbar,
  .jobs-pager {
    padding-inline: 12px;
  }
  .jobs-toolbar {
    gap: 0;
  }
  .jobs-search {
    flex: 1 0 100%;
  }
}

</style>
