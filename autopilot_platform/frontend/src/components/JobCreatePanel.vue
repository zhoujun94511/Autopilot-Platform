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

// ---- 分步向导 ----
const currentStep = ref(0);
const lastStep = 4;

// 工程源二选一：制品 / Runner 本地路径
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
const steps = computed(() => [
  { key: "meta", title: "基础信息" },
  { key: "source", title: "工程源" },
  { key: "app", title: "应用资源" },
  { key: "devices", title: isDeviceless.value ? "执行节点" : "设备" },
  { key: "review", title: "确认提交" },
]);
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
  () => canEdit.value && missing.value.length === 0 && !submitting.value,
);

// 每步有效性（用于步骤条勾选、下一步禁用）
const stepValidity = computed(() => [
  Boolean(form.value.name.trim() && form.value.platform),
  hasSource.value && !(artifactEntries.value.length && !form.value.entry_paths.length),
  true,
  true,
  canSubmit.value,
]);
const canNext = computed(() => stepValidity.value[currentStep.value]);
function stepDone(i: number) {
  return i < currentStep.value && stepValidity.value[i];
}

const stepHint = computed(() => {
  if (currentStep.value === 0 && !form.value.name.trim()) return "请先填写任务名称";
  if (currentStep.value === 1) {
    if (!hasSource.value) return "请选择工程制品或填写 Runner 本地路径";
    if (artifactEntries.value.length && !form.value.entry_paths.length) return "请至少勾选一个用例";
  }
  return "";
});

function goto(i: number) {
  currentStep.value = i;
}
function next() {
  if (canNext.value && currentStep.value < lastStep) currentStep.value += 1;
}
function prev() {
  if (currentStep.value > 0) currentStep.value -= 1;
}

function onSubmit(ev: Event) {
  if (currentStep.value < lastStep) {
    if (canNext.value) next();
    return;
  }
  exec.onCreateJob(ev);
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

    <!-- 模板 / 沿用上次 -->
    <div class="template-bar">
      <button
        v-if="hasLastJobConfig"
        type="button"
        class="ghost small"
        @click="onApplyLast"
      >
        ↺ 沿用上次配置
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
      <span class="tpl-spacer" />
      <button type="button" class="ghost small" @click="onSaveTemplate">存为模板</button>
    </div>

    <!-- 步骤条 -->
    <ol class="stepper">
      <li
        v-for="(s, i) in steps"
        :key="s.key"
        class="stepper-item"
        :class="{ current: i === currentStep, done: stepDone(i) }"
      >
        <button type="button" class="stepper-btn" @click="goto(i)">
          <span class="stepper-index">
            <svg v-if="stepDone(i)" viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="3" fill="none">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span class="stepper-title">{{ s.title }}</span>
        </button>
      </li>
    </ol>

    <form class="job-creation-form" @submit.prevent="onSubmit">
      <!-- Step 1: Meta -->
      <div v-show="currentStep === 0" class="form-section">
        <h3 class="form-section-title">基础信息</h3>
        <div class="form-grid-three">
          <div class="form-field">
            <label for="job-name">名称 <span class="req" aria-hidden="true">*</span></label>
            <input
              id="job-name"
              v-model="form.name"
              required
              aria-required="true"
              placeholder="例如: Nightly_Smoke"
            />
          </div>
          <div class="form-field">
            <label for="job-project"
              >项目空间 <span class="req" aria-hidden="true">*</span></label
            >
            <ApSelect
              id="job-project"
              v-model="form.project_id"
              required
              aria-label="项目空间"
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

      <!-- Step 2: Source -->
      <div v-show="currentStep === 1" class="form-section">
        <h3 class="form-section-title">
          工程源 <span class="title-req">必填 · 二选一</span>
        </h3>
        <div class="source-toggle" role="group" aria-label="工程源类型">
          <button
            type="button"
            class="source-tab"
            :class="{ active: sourceMode === 'artifact' }"
            :aria-pressed="sourceMode === 'artifact'"
            @click="setSourceMode('artifact')"
          >
            选工程制品
          </button>
          <button
            type="button"
            class="source-tab"
            :class="{ active: sourceMode === 'dir' }"
            :aria-pressed="sourceMode === 'dir'"
            @click="setSourceMode('dir')"
          >
            Runner 本机路径
          </button>
        </div>

        <div v-if="sourceMode === 'artifact'" class="form-field">
          <label for="job-artifact-pick">工程制品</label>
          <ApSelect
            id="job-artifact-pick"
            v-model="form.artifact_id"
            aria-label="工程制品"
            aria-describedby="src-hint"
            :options="artifactPickOptions"
          />
          <p id="src-hint" class="form-field-hint">无列表时先到「工程制品」页上传 zip。</p>
        </div>
        <div v-else class="form-field">
          <label for="job-dir">本机工程目录</label>
          <input id="job-dir" v-model="form.project_dir" placeholder="/data/projects/my-suite" aria-describedby="dir-hint" />
          <p id="dir-hint" class="form-field-hint">
            填写本机执行程序能看到的工程目录，适合不上传、直接在本机跑。
          </p>
        </div>

        <div v-if="sourceMode === 'artifact' && form.artifact_id" class="entry-pick" style="margin-top: 0.75rem">
          <div class="entry-pick-head">
            <span class="entry-pick-title">勾选要执行的用例</span>
            <span class="form-field-hint" style="margin: 0">
              {{ form.entry_paths.length }}/{{ artifactEntries.length }}
            </span>
            <button type="button" class="linkish" @click="exec.selectAllEntryPaths">全选</button>
            <button type="button" class="linkish" @click="exec.clearEntryPaths">清空</button>
          </div>
          <p v-if="artifactEntriesLoading" class="form-field-hint">正在加载用例清单…</p>
          <p v-else-if="artifactEntriesError" class="form-field-hint" style="color: var(--bad)">
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
      </div>

      <!-- Step 3: App build -->
      <div v-show="currentStep === 2" class="form-section">
        <h3 class="form-section-title">
          应用资源 <span class="title-optional">可选</span>
        </h3>
        <p v-if="isWeb" class="form-field-hint">
          Web 用例无需 apk / ipa 应用资源，本步可直接跳过；被测站点由用例内「浏览器打开」的 URL 决定。
        </p>
        <p v-else-if="isHttp" class="form-field-hint">
          接口用例无需 apk / ipa。被测地址由 api_env.yaml 或步骤里的 base_url 决定。
        </p>
        <template v-else>
          <div class="form-field">
            <label for="job-app-pick">apk / ipa / xapk（推荐指定）</label>
            <ApSelect
              id="job-app-pick"
              v-model="form.app_build_id"
              aria-label="应用资源"
              :options="appPickOptions"
            />
          </div>
          <p class="form-field-hint">
            安装包与工程制品分离。指定后 Runner 从应用资源库下载该版本并安装；可不指定——仅当设备已装目标应用且用例不执行安装。
          </p>
        </template>
      </div>

      <!-- Step 4: Devices（web 无移动设备概念，仅需可选指定执行节点） -->
      <div v-show="currentStep === 3" class="form-section">
        <RunTargetFields
          :model="form"
          :devices="dispatchDevices"
          :disabled="!canEdit"
          id-prefix="job"
        />
      </div>

      <!-- Step 5: Review + submit -->
      <div v-show="currentStep === 4" class="form-section">
        <h3 class="form-section-title">确认与提交</h3>
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

        <div class="form-field" style="margin-top: 0.75rem">
          <label for="job-webhook">完成后通知地址（可选）</label>
          <input id="job-webhook" v-model="form.webhook_url" placeholder="任务结束时通知，可留空用系统默认" />
        </div>
        <p v-if="!canEdit" class="submit-missing-hint">
          请先选择有写权限的项目；只读成员无法创建批跑。
        </p>
        <p v-else-if="missing.length" class="submit-missing-hint">还需填写：{{ missing.join("、") }}</p>
      </div>

      <!-- 向导导航 -->
      <div class="wizard-nav">
        <button type="button" class="ghost" :disabled="currentStep === 0" @click="prev">
          上一步
        </button>
        <div class="wizard-nav-right">
          <span v-if="stepHint && currentStep < lastStep" class="step-hint">{{ stepHint }}</span>
          <button
            v-if="currentStep < lastStep"
            type="button"
            class="primary"
            :disabled="!canNext"
            @click="next"
          >
            下一步
          </button>
          <button
            v-else
            type="submit"
            class="primary large-submit-btn"
            :disabled="!canSubmit"
            :title="
              !canEdit
                ? '当前项目无写权限'
                : missing.length
                  ? `还需填写：${missing.join('、')}`
                  : '提交批跑任务'
            "
          >
            <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none">
              <polyline points="22 2 15 22 11 13 2 9 22 2" />
              <line x1="22" y1="2" x2="11" y2="13" />
            </svg>
            {{ submitting ? "提交中…" : "提交批跑" }}
          </button>
        </div>
      </div>
    </form>

    <p v-if="jobMsg" class="msg" :class="jobMsgOk ? 'ok' : 'bad'">
      {{ jobMsg }}
    </p>
  </section>
</template>

<style scoped>
.template-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: -0.25rem 0 1rem;
  flex-wrap: wrap;
}

.template-bar .tpl-spacer {
  flex: 1;
}

.tpl-load .ap-select {
  min-width: 12rem;
}

.ghost.small {
  padding: 0.3rem 0.7rem;
  font-size: 0.8rem;
}

/* 步骤条 */
.stepper {
  display: flex;
  list-style: none;
  padding: 0;
  margin: 0 0 1.25rem;
  gap: 0.25rem;
  flex-wrap: wrap;
}

.stepper-item {
  flex: 1;
  min-width: 6rem;
}

.stepper-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: none;
  border: none;
  border-bottom: 2px solid var(--line);
  padding: 0.5rem 0.35rem;
  cursor: pointer;
  color: var(--muted);
  font-size: 0.82rem;
}

.stepper-item.current .stepper-btn {
  color: var(--accent-text, #1565c0);
  border-bottom-color: var(--accent);
  font-weight: 700;
}

.stepper-item.done .stepper-btn {
  color: var(--ok-soft-fg, #2e7d32);
}

.stepper-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 50%;
  background: var(--control-bg, var(--surface));
  border: 1px solid var(--line);
  font-size: 0.72rem;
  font-weight: 800;
  flex-shrink: 0;
}

.stepper-item.current .stepper-index {
  background: var(--accent);
  color: var(--on-accent, #fff);
  border-color: var(--accent);
}

.stepper-item.done .stepper-index {
  background: var(--ok-soft-bg, rgba(46, 125, 50, 0.15));
  color: var(--ok-soft-fg, #2e7d32);
  border-color: var(--ok-soft-fg, #2e7d32);
}

.stepper-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.job-creation-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-section {
  background-color: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.form-section-title {
  margin: 0 0 0.5rem !important;
  font-size: 0.88rem !important;
  font-weight: 700;
  color: var(--accent-text);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.4rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.title-req,
.title-optional {
  text-transform: none;
  letter-spacing: 0;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
}

.title-req {
  color: var(--bad);
  background: var(--danger-soft-bg, rgba(198, 40, 40, 0.1));
}

.title-optional {
  color: var(--muted);
  background: var(--chip-bg, rgba(120, 120, 120, 0.12));
}

.req {
  color: var(--bad);
}

.source-toggle {
  display: inline-flex;
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
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
  background: var(--accent);
  color: var(--on-accent, #fff);
}

.form-grid-three {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.form-grid-two {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-grid-devices {
  display: grid;
  grid-template-columns: 2fr 1fr auto 6rem;
  gap: 1rem;
  align-items: end;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.form-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.form-field-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin: -0.25rem 0 0;
  font-style: italic;
  white-space: normal;
  overflow-wrap: break-word;
}

.flex-one { min-width: 0; }
.flex-two { min-width: 0; }

.checkbox-field {
  padding-bottom: 0.55rem;
  justify-content: flex-end;
}

.checkbox-label {
  display: flex;
  flex-direction: row !important;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  user-select: none;
  font-weight: 700 !important;
  color: var(--text) !important;
}

.checkbox-label input[type="checkbox"] {
  width: auto;
  cursor: pointer;
}

.workers-field input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.advanced-block {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  background: var(--control-bg, var(--surface));
  margin-top: 0.75rem;
}

.advanced-block > summary {
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--accent-text, #1565c0);
  user-select: none;
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
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--control-bg);
  border: 1px solid var(--line);
  text-transform: uppercase;
}

.kind-mini-badge.case { color: var(--ok-soft-fg); }
.kind-mini-badge.suite { color: var(--accent-text); }
.kind-mini-badge.plan { color: var(--purple-soft-fg); }

.linkish {
  background: none;
  border: none;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
  text-decoration: underline;
}

/* 确认页 */
.review-summary {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.5rem 1.5rem;
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
}

.review-val.is-missing {
  color: var(--bad);
}

.review-val.is-optional {
  color: var(--muted);
  font-weight: 500;
}

/* 向导导航 */
.wizard-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  border-top: 1px solid var(--line);
  padding-top: 1rem;
  flex-wrap: wrap;
}

.wizard-nav-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.step-hint {
  font-size: 0.78rem;
  color: var(--bad);
}

.large-submit-btn {
  padding: 0.65rem 1.75rem;
  font-size: 0.92rem;
  font-weight: 700;
}

.primary:disabled,
.large-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.submit-missing-hint {
  margin: 0.5rem 0 0;
  font-size: 0.78rem;
  color: var(--bad);
}

.empty-devices {
  margin: 0;
}

@media (max-width: 768px) {
  .form-grid-three,
  .form-grid-two,
  .form-grid-devices,
  .review-summary {
    grid-template-columns: 1fr;
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  .checkbox-field {
    justify-content: flex-start;
  }

  .stepper-title {
    display: none;
  }

  .stepper-item {
    min-width: 0;
    flex: 0 0 auto;
  }
}

.panel.embedded {
  border: none;
  box-shadow: none;
  background: transparent;
  padding: 0;
  margin: 0;
}
</style>
