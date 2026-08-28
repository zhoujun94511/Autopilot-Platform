<script setup lang="ts">
defineOptions({ name: "JobsPanel" });

import { computed, ref, watch } from "vue";
import type { Job } from "../api";
import { listJobsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import { useAdminStore } from "../stores/adminStore";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import JobCreatePanel from "./JobCreatePanel.vue";
import JobLogViewer from "./JobLogViewer.vue";
import StatusPill from "./StatusPill.vue";
import { JOB_STATUS_FILTERS } from "../utils/status";
import { platformBadgeLabel } from "../utils/deviceDisplay";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const admin = useAdminStore();
const { jobsListVersion, jobMsg, jobMsgOk, logJobId } = storeToRefs(exec);

const caps = useCapabilities();
const canCreateJob = computed(() => Boolean(caps.canEditProject));
const search = ref("");
const statusFilter = ref("");
const createOpen = ref(false);

const list = usePagedList<Job>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listJobsPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
      q: search.value.trim() || undefined,
      status: statusFilter.value || undefined,
    }),
  resetSources: [() => filterProjectId.value],
  filterSources: [statusFilter],
  isUnfiltered: () => !statusFilter.value && !search.value.trim(),
});

const { items, total, page, pageSize, loading, hasLoaded, universeEmpty, reload, setPage, setPageSize } = list;

let searchTimer: ReturnType<typeof setTimeout> | undefined;
watch(search, () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    if (universeEmpty.value) return;
    void reload(true);
  }, 280);
});

watch(jobsListVersion, () => void reload(false));
void reload(true);

function openCreate() {
  jobMsg.value = "";
  const pid = filterProjectId.value.trim();
  if (pid) exec.form.project_id = pid;
  createOpen.value = true;
}

function closeCreate() {
  createOpen.value = false;
}

watch(
  jobMsg,
  (m) => {
    if (
      createOpen.value &&
      jobMsgOk.value &&
      String(m || "").startsWith("已创建任务")
    ) {
      createOpen.value = false;
    }
  },
);
</script>

<template>
  <section class="panel page-stack jobs-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>批跑</h2>
        <p class="lede">查看正在跑和已完成的任务。点「新建批跑」创建。</p>
      </div>
      <div class="page-hero-actions">
        <label class="toolbar-search">
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input v-model="search" type="search" placeholder="搜索名称 / ID / 节点…" />
        </label>
        <button
          v-if="canCreateJob"
          type="button"
          class="primary small"
          @click="openCreate"
        >
          新建批跑
        </button>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="新建批跑" />

    <div class="filter-chips" role="tablist" aria-label="任务状态筛选">
      <button
        v-for="f in JOB_STATUS_FILTERS"
        :key="f.value || 'all'"
        type="button"
        role="tab"
        class="filter-chip"
        :class="{ active: statusFilter === f.value }"
        :aria-selected="statusFilter === f.value"
        @click="statusFilter = f.value"
      >
        {{ f.label }}
      </button>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>状态</th>
            <th>平台</th>
            <th>项目 / 制品</th>
            <th>节点</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="7">
              <template v-if="total">无匹配任务，请调整搜索或状态筛选</template>
              <div v-else class="empty-stack">
                <span>暂无批跑任务</span>
                <button
                  v-if="canCreateJob"
                  type="button"
                  class="linkish-cta"
                  @click="openCreate"
                >
                  去新建批跑
                </button>
              </div>
            </td>
          </tr>
          <tr v-for="j in items" :key="j.id">
            <td class="mono font-semibold" :title="j.id">
              <button type="button" class="small" @click="admin.copyText(j.id)">
                {{ j.id.slice(0, 8) }}…
              </button>
            </td>
            <td class="job-name-cell">{{ j.name }}</td>
            <td>
              <StatusPill :status="j.status" />
            </td>
            <td>
              <span class="platform-mini-badge" :class="j.platform.toLowerCase()">
                {{ platformBadgeLabel(j.platform) }}
              </span>
            </td>
            <td
              class="mono artifact-info-cell"
              :title="[j.artifact_id, j.app_build_id, j.project_dir].filter(Boolean).join(' | ')"
            >
              <span v-if="j.project_id" class="pj-tag">{{ j.project_id }}</span>
              <span class="target-desc">{{ j.artifact_id || j.project_dir || "-" }}</span>
              <span
                v-if="j.app_build_id"
                class="pj-tag app-tag"
                :title="[j.app_package_id, j.app_build_id].filter(Boolean).join(' · ')"
              >
                {{
                  j.app_build_name
                    ? `${j.app_build_name}${j.app_version_name ? " v" + j.app_version_name : ""}`
                    : "app"
                }}
              </span>
            </td>
            <td class="mono runner-id-cell">{{ j.runner_id || "-" }}</td>
            <td class="actions-cell">
              <button
                v-if="exec.canCancel(j.status)"
                type="button"
                class="small danger"
                title="取消正在运行的任务"
                @click="exec.onCancelJob(j.id)"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                取消
              </button>

              <button
                v-if="exec.canRetry(j.status)"
                type="button"
                class="small primary"
                title="重试此失败/取消的任务"
                @click="exec.onRetryJob(j.id)"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38" />
                </svg>
                重试
              </button>

              <button
                v-if="exec.canViewReport(j.status)"
                type="button"
                class="small"
                title="查看测试报告"
                @click="exec.onViewReport(j.id)"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                报告
              </button>

              <button
                type="button"
                class="small"
                title="查看实时日志"
                @click="exec.onViewJobLog(j.id)"
              >
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                日志
              </button>

              <button
                v-if="caps.canShareWrite"
                type="button"
                class="small"
                title="去共享页，把这个任务分享给别人"
                @click="ops.selectJobForShare(j.id)"
              >
                分享
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <DataPager
      v-if="total > 0"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />

    <JobLogViewer
      v-if="logJobId"
      :job-id="logJobId"
      @close="exec.closeJobLog"
    />

    <Teleport to="body">
      <div v-if="createOpen" class="modal-mask" @click.self="closeCreate">
        <section
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="job-create-title"
        >
          <header class="modal-head">
            <div>
              <h3 id="job-create-title">新建批跑</h3>
              <p class="modal-sub">分步填写基础信息、工程源与执行目标后提交。</p>
            </div>
            <button type="button" class="icon-btn" aria-label="关闭" @click="closeCreate">✕</button>
          </header>
          <div class="modal-scroll">
            <JobCreatePanel embedded />
          </div>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.jobs-panel {
  width: 100%;
  max-width: none;
  gap: 0.85rem;
}

.filter-chips {
  margin-bottom: 0;
}

.font-semibold {
  font-weight: 600;
}

.job-name-cell {
  font-weight: 500;
  color: var(--text);
}

.platform-mini-badge {
  display: inline-block;
  min-width: 2.2em;
  text-align: center;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background-color: var(--chip-bg);
}

.platform-mini-badge.android {
  color: var(--ok-soft-fg);
  background-color: var(--ok-soft-bg);
}

.platform-mini-badge.ios {
  color: var(--purple-soft-fg);
  background-color: var(--purple-soft-bg);
}

.platform-mini-badge.web {
  color: var(--info-soft-fg);
  background-color: var(--info-soft-bg);
}

.platform-mini-badge.http {
  color: var(--accent-text);
  background-color: var(--accent-soft);
}

.artifact-info-cell {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pj-tag {
  font-family: var(--font);
  font-size: 0.68rem;
  font-weight: 700;
  background-color: var(--btn-bg);
  border: 1px solid var(--line);
  color: var(--muted);
  padding: 0.05rem 0.3rem;
  border-radius: 4px;
  margin-right: 0.4rem;
}

.target-desc {
  color: var(--mono);
}

.runner-id-cell {
  color: var(--muted);
}

.actions-cell {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

td.empty {
  text-align: center;
}

.linkish-cta {
  background: none;
  border: none;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0;
  margin: 0;
}

.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 1.5rem;
  overflow-y: auto;
  background: var(--overlay);
}

.modal-card {
  width: min(920px, 100%);
  margin: auto 0;
  background: var(--surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevated-shadow);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 3rem);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.1rem 1.2rem 0.85rem;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.modal-head h3 {
  margin: 0 0 0.3rem;
  font-size: 1rem;
  font-weight: 700;
  color: var(--text);
}

.modal-sub {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}

.icon-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1rem;
  padding: 0.2rem 0.4rem;
  border-radius: var(--radius-sm);
}

.icon-btn:hover {
  color: var(--text);
  background: var(--action-hover);
}

.modal-scroll {
  overflow-y: auto;
  padding: 0.85rem 1.2rem 1.2rem;
  min-height: 0;
}
</style>
