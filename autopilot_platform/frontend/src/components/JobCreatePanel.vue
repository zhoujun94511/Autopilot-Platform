<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useCapabilities } from "../composables/useCapabilities";
import { useExecStore } from "../stores/execution";
import { useProjectsStore } from "../stores/projectsStore";
import { parseUdids } from "../composables/devicePick";
import { isDevicelessPlatform, isHttpPlatform, isWebPlatform, PLATFORM_OPTIONS } from "../composables/runTargetOptions";
import { platformBadgeLabel } from "../utils/deviceDisplay";
import type { AppBuild, Artifact } from "../api";
import { confirmDialog } from "../composables/useNotify";
import ApSelect from "./common/ApSelect.vue";
import RunTargetFields from "./common/RunTargetFields.vue";

const exec = useExecStore();
const projectsStore = useProjectsStore();
const {
  form,
  artifacts,
  appBuilds,
  dispatchDevices,
  artifactEntries,
  artifactEntriesLoading,
  artifactEntriesError,
  submitting,
  jobMsg,
  jobMsgOk,
  jobTemplates,
  hasLastJobConfig,
} = storeToRefs(exec);
const { projects } = storeToRefs(projectsStore);
const caps = useCapabilities();


defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{
  (e: "pending-change", value: boolean): void;
  (e: "cancel"): void;
}>();
const submitLocked = ref(false);

// 工程源二选一：制品 / 执行节点上的路径
const sourceMode = ref<"artifact" | "dir">(
  form.value.project_dir && !form.value.artifact_id ? "dir" : "artifact",
);
function setSourceMode(mode: "artifact" | "dir") {
  if (sourceMode.value === mode) return;
  sourceMode.value = mode;
  if (mode === "artifact") {
    form.value.project_dir = "";
  } else {
    form.value.artifact_id = "";
    form.value.entry_paths = [];
  }
}
function syncSourceMode() {
  sourceMode.value =
    form.value.project_dir && !form.value.artifact_id ? "dir" : "artifact";
}

const filteredArtifacts = computed(() => {
  const pid = form.value.project_id.trim();
  const list = artifacts.value as Artifact[];
  if (!pid) return list;
  return list.filter((a) => !a.project_id || a.project_id === pid);
});

const filteredAppBuilds = computed(() => {
  const plat = (form.value.platform || "").toLowerCase();
  const pid = form.value.project_id.trim();
  return (appBuilds.value as AppBuild[]).filter((b) => {
    if (plat && b.platform && b.platform.toLowerCase() !== plat) return false;
    if (pid && b.project_id && b.project_id !== pid) return false;
    return true;
  });
});

const isWeb = computed(() => isWebPlatform(form.value.platform));
const isHttp = computed(() => isHttpPlatform(form.value.platform));
const isDeviceless = computed(() => isDevicelessPlatform(form.value.platform));
const selectedDeviceCount = computed(() => parseUdids(form.value.device_udids).length);

function artifactLabel(a: Artifact) {
  const short = a.id.slice(0, 8);
  return `${a.name || a.filename || "未命名"} · ${short}…`;
}

function appBuildLabel(b: AppBuild) {
  const ver = b.version_name
    ? ` v${b.version_name}${b.version_code ? `(${b.version_code})` : ""}`
    : "";
  const pkg = b.package_id ? ` · ${b.package_id}` : "";
  return `${b.name || b.filename}${ver}${pkg} · ${b.id.slice(0, 8)}…`;
}

const templateOptions = computed(() => [
  { value: "", label: "从模板载入…" },
  ...jobTemplates.value.map((t) => ({ value: t.name, label: t.name })),
]);
const projectOptions = computed(() => [
  { value: "", label: "请选择项目", disabled: true },
  ...projects.value.map((p) => ({
    value: p.id,
    label: `${p.id} (${p.name || "未命名"})`,
  })),
]);
const platformOptions = PLATFORM_OPTIONS;
const artifactPickOptions = computed(() => [
  { value: "", label: "— 请选择 —" },
  ...filteredArtifacts.value.map((a) => ({ value: a.id, label: artifactLabel(a) })),
]);
const appPickOptions = computed(() => [
  { value: "", label: "— 不指定（仅当设备已装且用例不安装）—" },
  ...filteredAppBuilds.value.map((b) => ({ value: b.id, label: appBuildLabel(b) })),
]);

const selectedAppBuild = computed(() =>
  filteredAppBuilds.value.find((b) => b.id === form.value.app_build_id) || null,
);

const hasSource = computed(
  () => Boolean(form.value.artifact_id.trim() || form.value.project_dir.trim()),
);

// 提交可用性：列出仍缺的必填项
const missing = computed(() => {
  const out: string[] = [];
  if (!form.value.name.trim()) out.push("名称");
  if (!hasSource.value) out.push("工程源");
  if (artifactEntries.value.length && !form.value.entry_paths.length) out.push("用例勾选");
  return out;
});
const canEdit = computed(() => Boolean(caps.canEditProject));
const canSubmit = computed(
  () => canEdit.value && missing.value.length === 0 && !submitting.value && !submitLocked.value,
);

async function onSubmit(ev: Event) {
  if (!canSubmit.value) {
    ev.preventDefault();
    return;
  }
  if (submitLocked.value) return;
  submitLocked.value = true;
  emit("pending-change", true);
  try {
    await exec.onCreateJob(ev);
  } finally {
    submitLocked.value = false;
    emit("pending-change", false);
  }
}

// ---- 模板栏 ----
const pickedTemplate = ref("");
async function onPickTemplate() {
  if (!pickedTemplate.value) return;
  await exec.applyJobTemplate(pickedTemplate.value);
  syncSourceMode();
}
async function onSaveTemplate() {
  await exec.saveJobAsTemplate();
}
async function onDeleteTemplate() {
  if (!pickedTemplate.value) return;
  const name = pickedTemplate.value;
  if (
    !(await confirmDialog(`删除模板「${name}」？此操作只影响本机保存的批跑模板。`, {
      title: "删除模板",
      okText: "删除",
      danger: true,
    }))
  ) {
    return;
  }
  exec.deleteJobTemplate(name);
  pickedTemplate.value = "";
}
async function onApplyLast() {
  await exec.applyLastJobConfig();
  syncSourceMode();
}

// 切换平台时清理不匹配的应用资源（设备列表会按平台自动过滤）
watch(
  () => form.value.platform,
  () => {
    const bid = form.value.app_build_id;
    if (bid) {
      const hit = (appBuilds.value as AppBuild[]).find((b) => b.id === bid);
      if (hit && hit.platform && hit.platform.toLowerCase() !== form.value.platform.toLowerCase()) {
        form.value.app_build_id = "";
      }
    }
  },
);
</script>

<template>
  <section id="job-create" class="panel" :class="{ embedded }">
    <h2 v-if="!embedded">新建批跑</h2>

    <details class="template-tools">
      <summary>配置模板</summary>
      <div class="template-bar">
        <button
          v-if="hasLastJobConfig"
          type="button"
          class="ghost small"
          @click="onApplyLast"
        >
          沿用上次配置
        </button>
        <label v-if="jobTemplates.length" class="tpl-load">
          <ApSelect
            v-model="pickedTemplate"
            size="compact"
            aria-label="从模板载入"
            :options="templateOptions"
            @change="onPickTemplate"
          />
        </label>
        <button
          v-if="pickedTemplate"
          type="button"
          class="linkish"
          @click="onDeleteTemplate"
        >
          删除该模板
        </button>
        <button type="button" class="ghost small" @click="onSaveTemplate">存为模板</button>
      </div>
    </details>

    <form class="job-creation-form" @submit.prevent="onSubmit">
      <div class="form-section">
        <div class="form-grid-three">
          <div class="form-field">
            <label for="job-name">名称 <span class="req" aria-hidden="true">*</span></label>
            <input
              id="job-name"
              v-model="form.name"
              data-autofocus
              required
              aria-required="true"
            />
          </div>
          <div class="form-field">
            <label for="job-project"
              >项目 <span class="req" aria-hidden="true">*</span></label
            >
            <ApSelect
              id="job-project"
              v-model="form.project_id"
              required
              aria-label="项目"
              :options="projectOptions"
            />
          </div>
          <div class="form-field">
            <label for="job-platform">平台 <span class="req" aria-hidden="true">*</span></label>
            <ApSelect
              id="job-platform"
              v-model="form.platform"
              required
              aria-label="平台"
              :options="platformOptions"
            />
          </div>
        </div>
      </div>

      <section class="form-section" aria-labelledby="job-source-title">
        <h3 id="job-source-title" class="form-section-title">工程来源</h3>
        <div class="source-toggle" role="group" aria-label="工程源类型">
          <button
            type="button"
            class="source-tab"
            :class="{ active: sourceMode === 'artifact' }"
            :aria-pressed="sourceMode === 'artifact'"
            @click="setSourceMode('artifact')"
          >
            工程制品
          </button>
          <button
            type="button"
            class="source-tab"
            :class="{ active: sourceMode === 'dir' }"
            :aria-pressed="sourceMode === 'dir'"
            @click="setSourceMode('dir')"
          >
            节点路径
          </button>
        </div>

        <div v-if="sourceMode === 'artifact'" class="form-field">
          <label for="job-artifact-pick">工程制品</label>
          <ApSelect
            id="job-artifact-pick"
            v-model="form.artifact_id"
            aria-label="工程制品"
            :aria-describedby="filteredArtifacts.length ? undefined : 'src-hint'"
            :options="artifactPickOptions"
          />
          <p v-if="!filteredArtifacts.length" id="src-hint" class="form-field-hint">请在「工程制品」页上传 ZIP 文件。</p>
        </div>
        <div v-else class="form-field">
          <label for="job-dir">工程目录</label>
          <input id="job-dir" v-model="form.project_dir" placeholder="/data/projects/my-suite" aria-describedby="dir-hint" />
          <p id="dir-hint" class="form-field-hint">
            路径须可由执行节点访问。
          </p>
        </div>

        <div v-if="sourceMode === 'artifact' && form.artifact_id" class="entry-pick">
          <div class="entry-pick-head">
            <span class="entry-pick-title">勾选要执行的用例</span>
            <span class="form-field-hint">
              {{ form.entry_paths.length }}/{{ artifactEntries.length }}
            </span>
            <button type="button" class="linkish" @click="exec.selectAllEntryPaths">全选</button>
            <button type="button" class="linkish" @click="exec.clearEntryPaths">清空</button>
          </div>
          <p v-if="artifactEntriesLoading" class="form-field-hint">正在加载用例清单…</p>
          <p v-else-if="artifactEntriesError" class="form-field-hint field-error">
            {{ artifactEntriesError }}
          </p>
          <p v-else-if="!artifactEntries.length" class="form-field-hint">
            该制品未发现 .tc / .ts / .tp 入口；提交后将按空工程处理。
          </p>
          <div v-else class="entry-pick-list">
            <label
              v-for="e in artifactEntries"
              :key="e.path"
              class="entry-pick-row"
              :class="{ checked: form.entry_paths.includes(e.path) }"
            >
              <input
                type="checkbox"
                :checked="form.entry_paths.includes(e.path)"
                @change="exec.toggleEntryPath(e.path)"
              />
              <span class="kind-mini-badge" :class="e.kind">{{ e.kind }}</span>
              <span class="entry-name">{{ e.name || e.path }}</span>
              <span class="mono entry-path">{{ e.path }}</span>
            </label>
          </div>
        </div>
      </section>

      <section class="form-section" aria-labelledby="job-execution-title">
        <h3 id="job-execution-title" class="form-section-title">执行设置</h3>
        <div v-if="!isDeviceless" class="form-field">
            <label for="job-app-pick">应用资源（可选）</label>
            <ApSelect
              id="job-app-pick"
              v-model="form.app_build_id"
              aria-label="应用资源"
              :options="appPickOptions"
            />
        </div>
        <RunTargetFields
          :model="form"
          :devices="dispatchDevices"
          :disabled="!canEdit"
          compact
          id-prefix="job"
        />
      </section>

      <details class="job-review">
        <summary>提交前核对</summary>
        <div class="review-summary">
          <div class="review-row">
            <span class="review-key">名称</span>
            <span class="review-val" :class="form.name.trim() ? '' : 'is-missing'">
              {{ form.name || "（未填）" }}
            </span>
          </div>
          <div class="review-row">
            <span class="review-key">平台</span>
            <span class="review-val">{{ platformBadgeLabel(form.platform) }}</span>
          </div>
          <div class="review-row">
            <span class="review-key">工程源</span>
            <span class="review-val" :class="hasSource ? '' : 'is-missing'">
              {{ form.artifact_id ? `制品 ${form.artifact_id.slice(0, 8)}…` : (form.project_dir || "未选工程源") }}
            </span>
          </div>
          <div class="review-row" v-if="artifactEntries.length">
            <span class="review-key">用例</span>
            <span class="review-val" :class="form.entry_paths.length ? '' : 'is-missing'">
              已选 {{ form.entry_paths.length }}/{{ artifactEntries.length }} 项
            </span>
          </div>
          <div class="review-row" v-if="!isDeviceless">
            <span class="review-key">应用资源</span>
            <span class="review-val is-optional">
              {{
                selectedAppBuild
                  ? appBuildLabel(selectedAppBuild)
                  : form.app_build_id
                    ? `应用 ${form.app_build_id.slice(0, 8)}…`
                    : "未指定（设备已装且不安装才可省略）"
              }}
            </span>
          </div>
          <div class="review-row">
            <span class="review-key">{{ isDeviceless ? "执行节点" : "设备" }}</span>
            <span class="review-val is-optional">
              <template v-if="isWeb">{{ form.preferred_runner_id || "未指定（任意具备 Web 能力的节点领取）" }}</template>
              <template v-else-if="isHttp">{{ form.preferred_runner_id || "未指定（任意具备 HTTP 能力的节点领取）" }}</template>
              <template v-else>
                {{
                  selectedDeviceCount
                    ? `${selectedDeviceCount} 台设备`
                    : "未指定（任意空闲节点领取）"
                }}
              </template>
            </span>
          </div>
          <div class="review-row" v-if="isWeb">
            <span class="review-key">浏览器</span>
            <span class="review-val is-optional">
              {{ form.backend_mode && form.backend_mode !== "auto" ? form.backend_mode : "默认（用例内指定）" }}
            </span>
          </div>
          <div class="review-row" v-if="isWeb">
            <span class="review-key">引擎</span>
            <span class="review-val is-optional">
              {{ form.web_engine === "playwright" ? "Playwright" : "Selenium" }}
            </span>
          </div>
          <div class="review-row" v-if="isHttp">
            <span class="review-key">API 环境</span>
            <span class="review-val is-optional">
              {{ form.backend_mode && form.backend_mode !== "auto" ? form.backend_mode : "默认（用例内切换）" }}
            </span>
          </div>
          <div class="review-row" v-if="!isDeviceless">
            <span class="review-key">并发</span>
            <span class="review-val is-optional">
              {{ form.parallel ? `并行 · ${form.parallel_workers || "自动"}` : "串行" }}
            </span>
          </div>
        </div>

      </details>

      <details class="job-notification">
        <summary>完成通知</summary>
        <div class="form-field">
          <label for="job-webhook">完成后通知地址（可选）</label>
          <input id="job-webhook" v-model="form.webhook_url" placeholder="留空使用系统默认地址" />
        </div>
      </details>

      <p v-if="jobMsg" class="msg" :class="jobMsgOk ? 'ok' : 'bad'" :role="jobMsgOk ? 'status' : 'alert'">
        {{ jobMsg }}
      </p>
      <footer class="job-form-actions">
        <p v-if="!canEdit" class="submit-missing-hint">
          {{ caps.isProjectViewer ? "当前项目为只读，无法创建批跑。" : "请先在顶栏选择项目。" }}
        </p>
        <p v-else-if="missing.length" class="submit-missing-hint">还需填写：{{ missing.join("、") }}</p>
        <div class="submit-buttons">
          <button
            v-if="embedded"
            type="button"
            class="ghost"
            :disabled="submitting || submitLocked"
            @click="emit('cancel')"
          >
            关闭
          </button>
          <button
            type="submit"
            class="primary"
            :disabled="!canSubmit"
          >
            {{ submitting ? "提交中…" : "提交批跑" }}
          </button>
        </div>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.template-tools {
  margin-block-end: 1rem;
}

.template-tools > summary,
.job-review > summary,
.job-notification > summary {
  color: var(--text);
  font-size: var(--font-size-body);
  font-weight: 600;
  cursor: pointer;
}

.template-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.5rem;
  flex-wrap: wrap;
}

.tpl-load .ap-select {
  min-width: 12rem;
}

.ghost.small {
  padding: 0.3rem 0.7rem;
  font-size: 0.8rem;
}

.job-creation-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-width: 0;
}

.form-section + .form-section,
.job-review,
.job-notification,
.job-form-actions {
  border-top: 1px solid var(--line-soft);
  padding-top: 1rem;
}

.panel .form-section-title {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: 650;
  color: var(--text);
}

.req {
  color: var(--bad);
}

.source-toggle {
  display: inline-flex;
  gap: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  overflow: hidden;
  width: fit-content;
}

.source-tab {
  background: var(--control-bg, var(--surface));
  border: none;
  padding: 0.4rem 0.9rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--muted);
  cursor: pointer;
}

.source-tab + .source-tab {
  border-left: 1px solid var(--line);
}

.source-tab.active {
  background: var(--nav-active-bg);
  color: var(--accent-text);
}

.form-grid-three {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  min-width: 0;
}

.form-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.form-field-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin: 0;
  white-space: normal;
  overflow-wrap: break-word;
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
  max-height: 200px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
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

.entry-name {
  font-weight: 600;
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
  max-width: 14rem;
}

.kind-mini-badge {
  font-size: var(--font-size-meta);
  color: var(--muted);
}

.linkish {
  background: none;
  border: none;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
  text-decoration: underline;
}

.review-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 1.5rem;
}

.review-summary,
.job-notification .form-field {
  margin-block-start: 0.75rem;
}

.review-row {
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
  font-size: 0.82rem;
  border-bottom: 1px dashed var(--line-soft, var(--line));
  padding-bottom: 0.35rem;
}

.review-key {
  color: var(--muted);
  min-width: 4.5rem;
  font-weight: 600;
}

.review-val {
  color: var(--text);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.review-val.is-missing {
  color: var(--bad);
}

.review-val.is-optional {
  color: var(--muted);
  font-weight: 500;
}

.job-form-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.submit-buttons {
  display: flex;
  gap: var(--space-2);
  margin-inline-start: auto;
}

.submit-missing-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--bad);
}

.panel.embedded {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
  margin: 0;
}

@media (max-width: 768px) {
  .form-grid-three,
  .review-summary {
    grid-template-columns: 1fr;
  }

  .entry-pick-row {
    grid-template-columns: auto auto minmax(0, 1fr);
  }

  .entry-path {
    grid-column: 3;
  }
}
</style>
