<script setup lang="ts">
defineOptions({ name: "SchedulesPanel" });

import { storeToRefs } from "pinia";
import { computed, ref, watch } from "vue";
import { listSchedulesPage, OPS_LIST_PAGE_SIZE, type Schedule } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import { PLATFORM_OPTIONS, isDevicelessPlatform } from "../composables/runTargetOptions";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import ApSelect from "./common/ApSelect.vue";
import ApModal from "./ApModal.vue";
import RunTargetFields from "./common/RunTargetFields.vue";

const projectsStore = useProjectsStore();
const { filterProjectId, projects } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const {
  schedulesListVersion,
  scheduleForm,
  scheduleEditId,
  scheduleMsg,
  scheduleMsgOk,
  scheduleArtifactEntries,
  scheduleArtifactEntriesLoading,
  scheduleArtifactEntriesError,
  artifacts,
  appBuilds,
  dispatchDevices,
} = storeToRefs(exec);
const caps = useCapabilities();
const canCreateSchedule = computed(() => Boolean(caps.canEditProject));
const formOpen = ref(false);
const formPending = ref(false);
const artifactNames = computed(() => new Map(artifacts.value.map((a) => [a.id, a.name || a.filename])));

const list = usePagedList<Schedule>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listSchedulesPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
    }),
  resetSources: [() => filterProjectId.value],
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

watch(schedulesListVersion, () => void reload(false));
void reload(true);

const scheduleAppOptions = computed(() => {
  const plat = (scheduleForm.value.platform || "").toLowerCase();
  const pid = (scheduleForm.value.project_id || filterProjectId.value || "").trim();
  return [
    { value: "", label: "— 不指定（设备已装且不安装才可省略）—" },
    ...appBuilds.value
      .filter((b) => {
        if (plat && b.platform && b.platform.toLowerCase() !== plat) return false;
        if (pid && b.project_id && b.project_id !== pid) return false;
        return true;
      })
      .map((b) => {
        const ver = b.version_name
          ? ` v${b.version_name}${b.version_code ? `(${b.version_code})` : ""}`
          : "";
        const pkg = b.package_id ? ` · ${b.package_id}` : "";
        return {
          value: b.id,
          label: `${b.name || b.filename}${ver}${pkg} · ${b.platform} · ${b.id.slice(0, 8)}…`,
        };
      }),
  ];
});
const scheduleProjectOptions = computed(() => [
  { value: "", label: "请选择项目", disabled: true },
  ...projects.value.map((p) => ({
    value: p.id,
    label: `${p.id} (${p.name || "未命名"})`,
  })),
]);
const schedulePlatformOptions = PLATFORM_OPTIONS;
const isDeviceless = computed(() => isDevicelessPlatform(scheduleForm.value.platform));

function openCreate() {
  exec.cancelEditSchedule();
  scheduleMsg.value = "";
  formOpen.value = true;
}

function openEdit(s: Schedule) {
  exec.beginEditSchedule(s);
  scheduleMsg.value = "";
  formOpen.value = true;
}

function closeForm() {
  if (formPending.value) return;
  formOpen.value = false;
  exec.cancelEditSchedule();
}

async function submitSchedule(event: Event) {
  if (formPending.value) return;
  formPending.value = true;
  try {
    await exec.onCreateSchedule(event);
  } finally {
    formPending.value = false;
  }
}

function executionSource(schedule: Schedule) {
  const artifactId = schedule.artifact_id;
  return artifactId ? (artifactNames.value.get(artifactId) || `制品 ${artifactId.slice(0, 8)}…`) : (schedule.project_dir || "—");
}

function closeRowActions(event: Event) {
  const actions = (event.target as HTMLElement | null)?.closest<HTMLDetailsElement>(".schedule-row-menu");
  if (!actions?.open) return;
  actions.open = false;
  actions.querySelector("summary")?.focus();
}

function runRowAction(event: MouseEvent, action: () => unknown) {
  closeRowActions(event);
  void action();
}

watch(scheduleMsg, (m) => {
  if (!formOpen.value || !scheduleMsgOk.value) return;
  const text = String(m || "");
  if (text === "计划已创建" || text === "计划已更新") {
    formOpen.value = false;
  }
});
</script>

<template>
  <section class="panel page-stack data-page schedules-panel" aria-labelledby="schedules-title">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2 id="schedules-title">定时计划</h2>
      </div>
      <div class="page-hero-actions">
        <button
          v-if="canCreateSchedule"
          type="button"
          class="primary small"
          @click="openCreate"
        >
          新建计划
        </button>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="新建或编辑计划" />

    <div v-if="error" class="list-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="linkish" :disabled="loading" @click="reload(false)">重试</button>
    </div>

    <div class="table-wrap" tabindex="0" role="region" aria-label="定时计划列表" :aria-busy="loading">
      <table :class="{ 'has-schedules': items.length }">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">状态</th>
            <th scope="col">次数</th>
            <th scope="col">下次执行</th>
            <th scope="col">执行源</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && !error">
            <td class="empty" colspan="6">
              <span v-if="hasLoaded">暂无定时计划</span>
              <span v-else role="status">正在加载定时计划…</span>
            </td>
          </tr>
          <tr v-for="s in items" :key="s.id">
            <td class="schedule-name-cell">{{ s.name }}</td>
            <td>
              <span class="status-badge" :class="s.enabled ? 'status-succeeded' : 'status-cancelled'">
                {{ s.enabled ? "运行中" : "已暂停" }}
              </span>
            </td>
            <td>{{ s.runs_done }} / {{ s.repeat || "∞" }}</td>
            <td class="mono next-run-cell">
              {{ s.next_run_at ? String(s.next_run_at).slice(0, 19).replace("T", " ") : "-" }}
            </td>
            <td
              class="mono artifact-info-cell"
              :title="[s.artifact_id, s.app_build_id, s.project_dir].filter(Boolean).join(' | ')"
            >
              <span>{{ executionSource(s) }}</span>
              <span
                v-if="s.app_build_id"
                class="source-meta"
                :title="s.app_package_id || s.app_build_id"
              >
                {{
                  s.app_build_name
                    ? `${s.app_build_name}${s.app_version_name ? " v" + s.app_version_name : ""}`
                    : `应用 ${s.app_build_id.slice(0, 8)}…`
                }}
              </span>
            </td>
            <td>
              <div class="schedule-action-btn-group">
                <button type="button" class="linkish" @click="openEdit(s)">编辑</button>
                <button type="button" class="linkish" @click="exec.onRunScheduleNow(s.id)">
                  立即执行
                </button>
                <details
                  class="schedule-row-menu"
                  name="schedule-row-actions"
                  @keydown.esc.stop="closeRowActions"
                >
                  <summary :aria-label="`${s.name} 的更多操作`">更多</summary>
                  <div class="schedule-row-menu-actions">
                    <button type="button" class="linkish" @click="runRowAction($event, () => exec.onToggleSchedule(s.id, s.enabled))">
                      {{ s.enabled ? "停用" : "启用" }}
                    </button>
                    <button
                      v-if="caps.canShareWrite"
                      type="button"
                      class="linkish"
                      @click="runRowAction($event, () => ops.selectScheduleForShare(s.id))"
                    >
                      分享
                    </button>
                    <button type="button" class="linkish delete-schedule" @click="runRowAction($event, () => exec.onDeleteSchedule(s.id))">
                      删除
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
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      @update:page="setPage"
      @update:page-size="setPageSize"
    />

    <ApModal
      v-if="formOpen"
      :title="scheduleEditId ? '编辑计划' : '新建定时计划'"
      variant="drawer"
      :close-on-backdrop="false"
      :close-on-esc="!formPending"
      @close="closeForm"
    >
      <form class="schedule-form-body" :aria-busy="formPending" @submit.prevent="submitSchedule">
        <div class="schedule-form-grid">
          <div class="s-field">
            <label for="schedule-name">计划名称 <span class="req" aria-hidden="true">*</span></label>
            <input id="schedule-name" v-model="scheduleForm.name" required data-autofocus />
          </div>
          <div class="s-field">
            <label for="schedule-project">项目 <span class="req" aria-hidden="true">*</span></label>
            <ApSelect
              id="schedule-project"
              v-model="scheduleForm.project_id"
              required
              aria-label="项目"
              :options="scheduleProjectOptions"
            />
          </div>
          <div class="s-field">
            <label for="schedule-platform">平台</label>
            <ApSelect
              id="schedule-platform"
              v-model="scheduleForm.platform"
              aria-label="平台"
              :options="schedulePlatformOptions"
            />
          </div>
        </div>

        <section class="schedule-form-section" aria-labelledby="schedule-timing-title">
          <h4 id="schedule-timing-title">调度</h4>
          <div class="schedule-form-grid">
            <div class="s-field">
              <label for="schedule-delay">初始延迟（秒）</label>
              <input id="schedule-delay" v-model.number="scheduleForm.delay_sec" type="number" min="0" />
            </div>
            <div class="s-field">
              <label for="schedule-interval">循环间隔（秒）</label>
              <input id="schedule-interval" v-model.number="scheduleForm.interval_sec" type="number" min="0" />
            </div>
            <div class="s-field">
              <label for="schedule-repeat">最大次数（0 为无限）</label>
              <input id="schedule-repeat" v-model.number="scheduleForm.repeat" type="number" min="0" />
            </div>
          </div>
          <label class="checkbox-label">
            <input v-model="scheduleForm.stop_on_fail" type="checkbox" />
            <span>失败即停</span>
          </label>
        </section>

        <section class="schedule-form-section" aria-labelledby="schedule-source-title">
          <h4 id="schedule-source-title">工程来源</h4>
          <div class="schedule-form-grid source-fields">
            <div class="s-field">
              <label for="schedule-artifact">工程制品 ID</label>
              <input id="schedule-artifact" v-model="scheduleForm.artifact_id" />
            </div>
            <div class="s-field">
              <label for="schedule-dir">执行节点上的工程路径</label>
              <input id="schedule-dir" v-model="scheduleForm.project_dir" placeholder="/opt/workspace/suite" />
            </div>
          </div>
          <p class="form-field-hint">填写制品 ID 或执行节点可访问的路径，至少填一项。</p>
          <div
            v-if="scheduleForm.artifact_id.trim()"
            class="entry-pick"
          >
            <div class="entry-pick-head">
              <span class="entry-pick-title">勾选要执行的用例</span>
              <span class="form-field-hint">
                {{ scheduleForm.entry_paths.length }}/{{ scheduleArtifactEntries.length }}
              </span>
              <button type="button" class="linkish" @click="exec.selectAllScheduleEntryPaths">
                全选
              </button>
              <button type="button" class="linkish" @click="exec.clearScheduleEntryPaths">
                清空
              </button>
            </div>
            <p v-if="scheduleArtifactEntriesLoading" class="form-field-hint">
              正在加载用例清单…
            </p>
            <p
              v-else-if="scheduleArtifactEntriesError"
              class="form-field-hint field-error"
            >
              {{ scheduleArtifactEntriesError }}
            </p>
            <p v-else-if="!scheduleArtifactEntries.length" class="form-field-hint">
              该制品未发现 .tc / .ts / .tp 入口；留空则执行全部发现用例。
            </p>
            <div v-else class="entry-pick-list">
              <label
                v-for="e in scheduleArtifactEntries"
                :key="e.path"
                class="entry-pick-row"
                :class="{ checked: scheduleForm.entry_paths.includes(e.path) }"
              >
                <input
                  type="checkbox"
                  :checked="scheduleForm.entry_paths.includes(e.path)"
                  @change="exec.toggleScheduleEntryPath(e.path)"
                />
                <span class="kind-mini-badge" :class="e.kind">{{ e.kind }}</span>
                <span class="entry-name">{{ e.name || e.path }}</span>
                <span class="mono entry-path">{{ e.path }}</span>
              </label>
            </div>
          </div>
        </section>

        <section class="schedule-form-section" aria-labelledby="schedule-execution-title">
          <h4 id="schedule-execution-title">执行设置</h4>
          <div v-if="!isDeviceless" class="s-field">
            <label for="schedule-app">应用资源（可选）</label>
            <ApSelect
              id="schedule-app"
              v-model="scheduleForm.app_build_id"
              aria-label="应用资源"
              :options="scheduleAppOptions"
            />
          </div>
          <RunTargetFields
            :model="scheduleForm"
            :devices="dispatchDevices"
            compact
            id-prefix="schedule"
          />
        </section>

        <details class="schedule-notification">
          <summary>完成通知</summary>
          <div class="s-field">
            <label for="schedule-webhook">完成后通知地址（可选）</label>
            <input id="schedule-webhook" v-model="scheduleForm.webhook_url" />
          </div>
        </details>

        <p
          v-if="scheduleMsg"
          class="msg"
          :class="scheduleMsgOk ? 'ok' : 'bad'"
          :role="scheduleMsgOk ? 'status' : 'alert'"
        >
          {{ scheduleMsg }}
        </p>
        <footer class="modal-actions">
          <button type="button" class="ghost" :disabled="formPending" @click="closeForm">取消</button>
          <button type="submit" class="primary" :disabled="formPending">
            {{ formPending ? "保存中…" : scheduleEditId ? "保存修改" : "创建计划" }}
          </button>
        </footer>
      </form>
    </ApModal>
  </section>
</template>

<style scoped>
.schedules-panel {
  width: 100%;
  max-width: none;
}

.schedules-panel .table-wrap:focus-visible {
  outline-offset: -2px;
}

.schedules-panel .has-schedules {
  min-width: 690px;
}

.list-error {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-3);
  color: var(--bad);
}

.schedule-name-cell {
  font-weight: 600;
}

.next-run-cell {
  color: var(--muted);
}

.artifact-info-cell {
  max-width: 200px;
  color: var(--muted);
}

.artifact-info-cell > span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-meta {
  margin-block-start: 0.25rem;
  font-size: var(--font-size-meta);
}

.schedule-action-btn-group {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  white-space: nowrap;
}

.schedule-row-menu > summary {
  cursor: pointer;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.schedule-row-menu-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.schedule-row-menu-actions .delete-schedule {
  color: var(--bad);
}

td.empty {
  text-align: center;
  height: 112px;
}

.schedule-form-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.schedule-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr));
  gap: var(--space-3);
  align-items: flex-end;
}

.schedule-form-grid.source-fields {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
}

.schedule-form-section,
.schedule-notification,
.modal-actions {
  border-top: 1px solid var(--line-soft);
  padding-top: 0.85rem;
}

.schedule-form-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.schedule-form-section h4 {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-body);
  font-weight: 650;
}

.schedule-notification summary {
  cursor: pointer;
  font-weight: 600;
}

.schedule-notification .s-field {
  margin-block-start: var(--space-2);
}

.s-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  min-width: 0;
}

.s-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  width: fit-content;
}

.checkbox-label input[type="checkbox"] {
  width: auto;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.msg {
  margin: 0;
  font-size: 0.82rem;
}
.msg.ok {
  color: var(--ok);
}
.msg.bad {
  color: var(--bad);
}

.form-field-hint {
  margin: 0;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.field-error {
  color: var(--bad);
}

.entry-pick-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.35rem;
}

.entry-pick-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.entry-pick-list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  max-height: 180px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: 0.35rem;
  background: var(--control-bg, var(--surface));
}

.entry-pick-row {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) minmax(0, 9rem);
  gap: 0.5rem;
  align-items: center;
  padding: 0.35rem 0.55rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.82rem;
}

.entry-pick-row:hover {
  background: var(--nav-hover);
}

.entry-pick-row.checked {
  background: var(--indigo-soft-bg, var(--nav-active-bg));
}

.kind-mini-badge {
  font-size: 0.68rem;
  text-transform: none;
  color: var(--muted);
}

.entry-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-path {
  font-size: 0.72rem;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.linkish {
  background: none;
  border: none;
  color: var(--accent-text);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
}

@media (max-width: 560px) {
  .entry-pick-row {
    grid-template-columns: auto auto minmax(0, 1fr);
  }

  .entry-path {
    grid-column: 3;
  }
}
</style>
