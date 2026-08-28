<script setup lang="ts">
/**
 * 设计域入队批跑配置（G1）：与 JobCreatePanel 共用 exec.form，避免跨 Tab 选制品/设备。
 */
import { storeToRefs } from "pinia";
import { computed, onMounted, watch } from "vue";
import type { AppBuild, Artifact } from "../../api";
import { parseUdids } from "../../composables/devicePick";
import { isDevicelessPlatform, PLATFORM_OPTIONS } from "../../composables/runTargetOptions";
import { useExecStore } from "../../stores/execution";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import ApSelect from "../common/ApSelect.vue";
import RunTargetFields from "../common/RunTargetFields.vue";
import { deriveArtifactRunReadiness } from "./artifactRunReadiness";

const props = withDefaults(
  defineProps<{
    /** 当前可入队的 APPROVED logical_case_id 数量 */
    approvedCount?: number;
    disabled?: boolean;
  }>(),
  {
    approvedCount: 0,
    disabled: false,
  },
);

const exec = useExecStore();
const projectsStore = useProjectsStore();
const shell = useShellStore();
const { form, artifacts, appBuilds, dispatchDevices } = storeToRefs(exec);
const { filterProjectId } = storeToRefs(projectsStore);

const projectId = computed(() => (filterProjectId.value || "").trim());

const filteredArtifacts = computed(() => {
  const pid = projectId.value || form.value.project_id.trim();
  const list = artifacts.value as Artifact[];
  if (!pid) return list;
  return list.filter((a) => !a.project_id || a.project_id === pid);
});

const filteredAppBuilds = computed(() => {
  const plat = (form.value.platform || "").toLowerCase();
  const pid = projectId.value || form.value.project_id.trim();
  return (appBuilds.value as AppBuild[]).filter((b) => {
    if (plat && b.platform && b.platform.toLowerCase() !== plat) return false;
    if (pid && b.project_id && b.project_id !== pid) return false;
    return true;
  });
});

const selectedArtifact = computed(() => {
  const aid = String(form.value.artifact_id || "").trim();
  if (!aid) return null;
  return filteredArtifacts.value.find((a) => a.id === aid) || null;
});

const deviceCount = computed(() => parseUdids(form.value.device_udids).length);

const isDeviceless = computed(() => isDevicelessPlatform(form.value.platform));

const runReadiness = computed(() =>
  deriveArtifactRunReadiness(
    { by_review_status: { APPROVED: props.approvedCount } } as any,
    artifacts.value,
    projectId.value,
  ),
);

const configReady = computed(
  () =>
    Boolean(String(form.value.artifact_id || "").trim()) &&
    (isDeviceless.value || deviceCount.value > 0),
);

const manifestHint = computed(() => {
  const art = selectedArtifact.value;
  if (!art) return "";
  const st = String(art.manifest_status || "").trim() || "unknown";
  if (st === "valid") {
    return "工程清单校验通过。控件绑定是否齐全，以清单里的可跑程度为准。";
  }
  const warns = (art.manifest_warnings || []).slice(0, 2);
  const errs = (art.manifest_errors || []).slice(0, 2);
  const bits = [...errs, ...warns].filter(Boolean);
  if (bits.length) {
    return `清单状态：${st}：${bits.join("；")}`;
  }
  return `清单状态：${st}。建议在 IDE 重新上传完整工程后再入队。`;
});

function artifactLabel(a: Artifact) {
  const short = a.id.slice(0, 8);
  const man = a.manifest_status ? ` · ${a.manifest_status}` : "";
  return `${a.name || a.filename || "未命名"} · ${short}…${man}`;
}

function appBuildLabel(b: AppBuild) {
  const ver = b.version_name
    ? ` v${b.version_name}${b.version_code ? `(${b.version_code})` : ""}`
    : "";
  const pkg = b.package_id ? ` · ${b.package_id}` : "";
  return `${b.name || b.filename}${ver}${pkg} · ${b.id.slice(0, 8)}…`;
}

const enqueueArtifactOptions = computed(() => [
  { value: "", label: "请选择 IDE 上传的制品…" },
  ...filteredArtifacts.value.map((a) => ({ value: a.id, label: artifactLabel(a) })),
]);
const enqueuePlatformOptions = PLATFORM_OPTIONS;
const enqueueAppOptions = computed(() => [
  { value: "", label: "不指定（设备已装且不安装才可省略）" },
  ...filteredAppBuilds.value.map((b) => ({ value: b.id, label: appBuildLabel(b) })),
]);

function syncProjectContext() {
  const pid = projectId.value;
  if (pid && form.value.project_id !== pid) {
    form.value.project_id = pid;
  }
}

async function refreshRunResources() {
  syncProjectContext();
  await shell.refreshScopes(["artifacts", "app-builds", "devices"]);
}

watch(
  () => filterProjectId.value,
  () => void refreshRunResources(),
);

onMounted(() => void refreshRunResources());

defineExpose({ configReady, refreshRunResources });

</script>

<template>
  <section class="surface-card enqueue-run-config" aria-labelledby="enqueue-run-config-title">
    <div class="card-title-row">
      <h3 id="enqueue-run-config-title">高级可选：远程批跑配置</h3>
      <span v-if="approvedCount > 0" class="pill">{{ approvedCount }} 条已审核通过</span>
      <span v-else class="pill">暂无已审核用例</span>
    </div>
    <p class="lede">
      审核通过后，还需要上传工程才能远程跑。安装包请在应用资源库单独选版本，不必打进工程 zip。
    </p>

    <details
      v-if="approvedCount > 0 && filteredArtifacts.length === 0"
      class="ide-guide"
      open
    >
      <summary>当前项目尚无工程制品 · AutoPilot IDE 上传步骤</summary>
      <p class="meta-line">{{ runReadiness.hint }}</p>
      <ol>
        <li v-for="(step, i) in runReadiness.ideUploadSteps" :key="i">{{ step }}</li>
      </ol>
      <button type="button" class="ghost small" @click="shell.activeTab = 'artifacts'">
        查看制品列表
      </button>
    </details>

    <div class="config-grid">
      <label class="field">
        工程制品 <span class="req">*</span>
        <ApSelect
          v-model="form.artifact_id"
          :disabled="disabled || !filteredArtifacts.length"
          aria-label="工程制品"
          :options="enqueueArtifactOptions"
        />
      </label>

      <label class="field">
        平台 <span class="req">*</span>
        <ApSelect
          v-model="form.platform"
          :disabled="disabled"
          aria-label="平台"
          :options="enqueuePlatformOptions"
        />
      </label>

      <label v-if="!isDeviceless" class="field">
        应用资源（可选）
        <ApSelect
          v-model="form.app_build_id"
          :disabled="disabled"
          aria-label="应用资源"
          :options="enqueueAppOptions"
        />
      </label>
    </div>

    <p v-if="manifestHint" class="manifest-hint" :class="{ warn: selectedArtifact?.manifest_status !== 'valid' }">
      {{ manifestHint }}
    </p>

    <RunTargetFields
      class="enqueue-run-target"
      :model="form"
      :devices="dispatchDevices"
      :disabled="disabled"
      compact
      id-prefix="enqueue"
    />

    <div class="status-row">
      <span class="pill" :class="configReady ? 'ok' : ''">
        {{ configReady ? "配置就绪，可入队" : "请选择制品" + (isDeviceless ? "" : "与设备") }}
      </span>
      <button type="button" class="ghost small" :disabled="disabled" @click="refreshRunResources">
        刷新制品/设备
      </button>
      <button type="button" class="linkish small" @click="shell.activeTab = 'jobs'">
        打开批跑页高级选项
      </button>
    </div>
  </section>
</template>

<style scoped>
.enqueue-run-config {
  padding: 1rem 1.05rem;
}

.lede {
  margin: -0.25rem 0 0.85rem;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.45;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.65rem;
  margin-bottom: 0.75rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}

.field .ap-select {
  font-weight: 400;
}

.req {
  color: var(--bad);
}

.manifest-hint {
  margin: 0 0 0.75rem;
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius-sm);
  font-size: 0.76rem;
  line-height: 1.4;
  background: var(--surface-soft);
  border: 1px solid var(--border-weak);
  color: var(--muted);
}

.manifest-hint.warn {
  border-color: color-mix(in srgb, var(--warn, orange) 35%, var(--border-weak));
  color: var(--text);
}

.web-hint {
  margin: 0 0 0.65rem;
  font-size: 0.78rem;
  color: var(--muted);
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.65rem;
}

.linkish.small {
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font: inherit;
  font-size: 0.78rem;
  cursor: pointer;
  text-decoration: underline;
}

.ide-guide {
  margin: 0 0 0.85rem;
  padding: 0.65rem 0.75rem;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--warn, orange) 35%, var(--border-weak));
  background: var(--surface-soft);
}

.ide-guide summary {
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.ide-guide ol {
  margin: 0.55rem 0 0.65rem;
  padding-left: 1.25rem;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
}

.ide-guide .meta-line {
  margin: 0.45rem 0 0;
  font-size: 0.78rem;
  color: var(--muted);
}

.enqueue-run-target {
  margin-top: 0.25rem;
}
</style>
