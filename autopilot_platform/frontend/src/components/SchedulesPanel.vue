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
  appBuilds,
  dispatchDevices,
} = storeToRefs(exec);
const caps = useCapabilities();
const canCreateSchedule = computed(() => Boolean(caps.canEditProject));
const formOpen = ref(false);

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

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

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
  formOpen.value = true;
}

function closeForm() {
  formOpen.value = false;
  exec.cancelEditSchedule();
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
  <section class="panel page-stack schedules-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>计划</h2>
        <p class="lede">按时间自动跑任务。点「新建」在弹窗里设置。</p>
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

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>状态</th>
            <th>次数</th>
            <th>下次执行</th>
            <th>执行源</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="6">
              <div class="empty-stack">
                <span>暂无定时计划</span>
                <button
                  v-if="canCreateSchedule"
                  type="button"
                  class="linkish-cta"
                  @click="openCreate"
                >
                  去新建计划
                </button>
              </div>
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
              <template v-if="s.artifact_id || s.project_dir || s.app_build_id">
                <span v-if="s.artifact_id">制品 {{ s.artifact_id.slice(0, 8) }}…</span>
                <span v-else-if="s.project_dir">{{ s.project_dir }}</span>
                <span v-else>-</span>
                <span
                  v-if="s.app_build_id"
                  class="app-tag"
                  :title="s.app_package_id || s.app_build_id"
                >
                  +{{
                    s.app_build_name
                      ? `${s.app_build_name}${s.app_version_name ? " v" + s.app_version_name : ""}`
                      : `app ${s.app_build_id.slice(0, 8)}…`
                  }}
                </span>
              </template>
              <template v-else>-</template>
            </td>
            <td>
              <div class="schedule-action-btn-group">
                <button type="button" class="small" @click="openEdit(s)">编辑</button>
                <button type="button" class="small primary" @click="exec.onRunScheduleNow(s.id)">
                  立即执行
                </button>
                <button
                  type="button"
                  class="small"
                  :class="s.enabled ? 'danger' : ''"
                  @click="exec.onToggleSchedule(s.id, s.enabled)"
                >
                  {{ s.enabled ? "停用" : "启用" }}
                </button>
                <button
                  v-if="caps.canShareWrite"
                  type="button"
                  class="small"
                  title="去共享页，把这个计划分享给别人"
                  @click="ops.selectScheduleForShare(s.id)"
                >
                  分享
                </button>
                <button type="button" class="small danger" @click="exec.onDeleteSchedule(s.id)">
                  删除
                </button>
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

    <Teleport to="body">
      <div v-if="formOpen" class="modal-mask" @click.self="closeForm">
        <section
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="schedule-form-title"
        >
          <header class="modal-head">
            <div>
              <h3 id="schedule-form-title">
                {{ scheduleEditId ? "编辑计划" : "新建定时计划" }}
              </h3>
              <p class="modal-sub">
                配置调度、执行源与目标设备（与批跑同一套选择器；可不指定，到点自动领取）。
              </p>
            </div>
            <button type="button" class="icon-btn" aria-label="关闭" @click="closeForm">✕</button>
          </header>

          <form class="modal-body" @submit.prevent="exec.onCreateSchedule">
            <div class="schedule-form-grid">
              <div class="s-field">
                <label>计划名称 *</label>
                <input v-model="scheduleForm.name" required placeholder="Smoke_Nightly" />
              </div>
              <div class="s-field">
                <label>工程制品 ID</label>
                <input
                  v-model="scheduleForm.artifact_id"
                  placeholder="上传后点选或粘贴"
                />
              </div>
              <div class="s-field" v-if="!isDeviceless">
                <label>应用资源（可选）</label>
                <ApSelect
                  v-model="scheduleForm.app_build_id"
                  aria-label="应用资源"
                  :options="scheduleAppOptions"
                />
              </div>
              <div class="s-field">
                <label>Runner 本地工程路径</label>
                <input
                  v-model="scheduleForm.project_dir"
                  placeholder="/opt/workspace/suite"
                />
              </div>
              <div class="s-field">
                <label>项目空间 <span class="req">*</span></label>
                <ApSelect
                  v-model="scheduleForm.project_id"
                  required
                  aria-label="项目空间"
                  :options="scheduleProjectOptions"
                />
              </div>
              <div class="s-field">
                <label>平台</label>
                <ApSelect
                  v-model="scheduleForm.platform"
                  aria-label="平台"
                  :options="schedulePlatformOptions"
                />
              </div>
              <div class="s-field flex-wide device-picker-field">
                <RunTargetFields
                  :model="scheduleForm"
                  :devices="dispatchDevices"
                  compact
                  id-prefix="schedule"
                />
              </div>
              <div class="s-field">
                <label>完成后通知地址</label>
                <input v-model="scheduleForm.webhook_url" placeholder="可选" />
              </div>
              <div class="s-field">
                <label>初始延迟（秒）</label>
                <input v-model.number="scheduleForm.delay_sec" type="number" min="0" />
              </div>
              <div class="s-field">
                <label>循环间隔（秒）</label>
                <input v-model.number="scheduleForm.interval_sec" type="number" min="0" />
              </div>
              <div class="s-field">
                <label>最大次数（0=无限）</label>
                <input v-model.number="scheduleForm.repeat" type="number" min="0" />
              </div>
              <div class="s-field checkbox-field">
                <label class="checkbox-label">
                  <input v-model="scheduleForm.stop_on_fail" type="checkbox" />
                  <span>失败即停</span>
                </label>
              </div>
            </div>

            <div
              v-if="scheduleForm.artifact_id.trim()"
              class="entry-pick"
              style="margin-top: 0.75rem"
            >
              <div class="entry-pick-head">
                <span class="entry-pick-title">勾选要执行的用例</span>
                <span class="form-field-hint" style="margin: 0">
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
                class="form-field-hint"
                style="color: var(--bad)"
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

            <p
              v-if="scheduleMsg"
              class="msg"
              :class="scheduleMsgOk ? 'ok' : 'bad'"
            >
              {{ scheduleMsg }}
            </p>
            <footer class="modal-actions">
              <button type="button" class="ghost" @click="closeForm">取消</button>
              <button type="submit" class="primary">
                {{ scheduleEditId ? "保存修改" : "创建计划" }}
              </button>
            </footer>
          </form>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.schedules-panel {
  width: 100%;
  max-width: none;
}

.schedule-name-cell {
  font-weight: 600;
}

.next-run-cell {
  color: var(--warning-soft-fg);
}

.artifact-info-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
}

.app-tag {
  margin-left: 0.35rem;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--accent-text);
}

.schedule-action-btn-group {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
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

td.empty {
  text-align: center;
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
  width: min(820px, 100%);
  margin: auto 0;
  background: var(--surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevated-shadow);
  max-height: calc(100vh - 3rem);
  display: flex;
  flex-direction: column;
}

.device-picker-field {
  flex: 1 1 100%;
  min-width: 100%;
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

.modal-body {
  padding: 1.1rem 1.2rem 1.2rem;
  overflow-y: auto;
}

.schedule-form-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
}

.s-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex: 1;
  min-width: 140px;
}

.s-field.flex-wide {
  flex: 2;
  min-width: 220px;
}

.s-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.checkbox-field {
  padding-bottom: 0.55rem;
  min-width: 140px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-weight: 700 !important;
  color: var(--text) !important;
}

.checkbox-label input[type="checkbox"] {
  width: auto;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}

.msg {
  margin: 0.75rem 0 0;
  font-size: 0.82rem;
}
.msg.ok {
  color: var(--ok);
}
.msg.bad {
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
  border-radius: 6px;
  padding: 0.35rem;
  background: var(--control-bg, var(--surface));
}

.entry-pick-row {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
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
  text-transform: uppercase;
  opacity: 0.8;
}

.entry-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-path {
  font-size: 0.72rem;
  color: var(--muted);
}

.linkish {
  background: none;
  border: none;
  color: var(--accent, #3b6);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
}
</style>
