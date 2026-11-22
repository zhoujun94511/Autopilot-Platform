<script setup lang="ts">
defineOptions({ name: "ReportsPanel" });

import { computed, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { api, apiErrorMessage, sessionFetch, type Report } from "../api";
import { listReportsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";
import { useShellStore } from "../stores/shellStore";
import { usePagedList } from "../composables/usePagedList";
import { workspaceScopeVersion } from "../composables/mcProjectsState";
import { useExecStore } from "../stores/execution";
import DataPager from "./common/DataPager.vue";
import JobQualityCard from "./JobQualityCard.vue";
import ApSelect from "./common/ApSelect.vue";
import ApModal from "./ApModal.vue";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const shell = useShellStore();
const { activeTab } = storeToRefs(shell);
const exec = useExecStore();
const {
  reportsListVersion,
  reportFilter,
  appBuilds,
  artifacts,
  compareForm,
  compareResult,
  compareMsg,
  compareOk,
} = storeToRefs(exec);

const activeTool = ref<"quality" | "compare" | null>(null);
const comparePending = ref(false);

const hasFilters = computed(() => Boolean(
  reportFilter.value.app_build_id || reportFilter.value.artifact_id || reportFilter.value.platform,
));

function clearFilters() {
  reportFilter.value.app_build_id = "";
  reportFilter.value.artifact_id = "";
  reportFilter.value.platform = "";
}

const list = usePagedList<Report>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listReportsPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
      artifactId: reportFilter.value.artifact_id.trim() || undefined,
      appBuildId: reportFilter.value.app_build_id.trim() || undefined,
      platform: reportFilter.value.platform.trim() || undefined,
    }),
  resetSources: [workspaceScopeVersion],
  filterSources: [
    () => reportFilter.value.app_build_id,
    () => reportFilter.value.artifact_id,
    () => reportFilter.value.platform,
  ],
  isUnfiltered: () =>
    !reportFilter.value.app_build_id.trim() &&
    !reportFilter.value.artifact_id.trim() &&
    !reportFilter.value.platform.trim(),
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

watch(reportsListVersion, () => void reload(false));
void reload(true);

function resetComparison() {
  compareForm.value.left = "";
  compareForm.value.right = "";
  compareResult.value = null;
  compareMsg.value = "";
}

function openCompare(jobId?: string) {
  if (comparePending.value) return;
  if (jobId) exec.pickCompare(jobId);
  activeTool.value = "compare";
}

function closeTools() {
  if (!comparePending.value) activeTool.value = null;
}

function goToQualityTarget(tab: string) {
  closeTools();
  activeTab.value = tab;
}

async function runComparison(event: Event) {
  if (comparePending.value) return;
  const scope = workspaceScopeVersion.value;
  comparePending.value = true;
  try {
    await exec.onCompareReports(event);
    if (scope !== workspaceScopeVersion.value) resetComparison();
  } finally {
    comparePending.value = false;
  }
}

watch([() => compareForm.value.left, () => compareForm.value.right], () => {
  compareResult.value = null;
  compareMsg.value = "";
});
watch(workspaceScopeVersion, () => {
  activeTool.value = null;
  resetComparison();
}, { flush: "sync" });
onDeactivated(() => { activeTool.value = null; });

type EvidenceAtt = {
  kind?: string;
  path?: string;
  case?: string;
  case_name?: string;
  intent_id?: string;
  previewUrl?: string;
  videoUrl?: string;
};

type EvidenceFile = {
  path: string;
  kind?: string;
  previewUrl?: string;
  videoUrl?: string;
};

const evidenceJobId = ref("");
const evidenceLoading = ref(false);
const evidenceError = ref("");
const evidenceAtts = ref<EvidenceAtt[]>([]);
const evidenceFiles = ref<EvidenceFile[]>([]);
const evidenceSteps = ref<
  {
    case?: string;
    intent_id?: string;
    fail_reason?: string;
    screenshot_path?: string;
    dom_path?: string;
    previewUrl?: string;
  }[]
>([]);
const blobUrls: string[] = [];
let evidenceRequest: AbortController | null = null;

function revokeEvidenceBlobs() {
  while (blobUrls.length) {
    const u = blobUrls.pop();
    if (u) URL.revokeObjectURL(u);
  }
}

function evidenceApiPath(jobId: string, filePath: string): string {
  let rel = (filePath || "").replace(/\\/g, "/").replace(/^\/+/, "");
  for (const p of ["reports/evidence/", "evidence/"]) {
    if (rel.startsWith(p)) {
      rel = rel.slice(p.length);
      break;
    }
  }
  return `/api/v1/jobs/${jobId}/evidence/${rel.split("/").map(encodeURIComponent).join("/")}`;
}

async function loadMediaBlob(jobId: string, filePath: string, signal: AbortSignal): Promise<string> {
  if (!filePath || signal.aborted) return "";
  try {
    const res = await sessionFetch(evidenceApiPath(jobId, filePath), { signal });
    if (!res.ok) return "";
    const blob = await res.blob();
    if (signal.aborted) return "";
    const url = URL.createObjectURL(blob);
    blobUrls.push(url);
    return url;
  } catch {
    return "";
  }
}

async function loadPreview(jobId: string, filePath: string, signal: AbortSignal): Promise<string> {
  if (!filePath || !/\.(png|jpe?g|gif|webp)$/i.test(filePath)) return "";
  return loadMediaBlob(jobId, filePath, signal);
}

async function loadVideo(jobId: string, filePath: string, signal: AbortSignal): Promise<string> {
  if (!filePath || !/\.mp4$/i.test(filePath)) return "";
  return loadMediaBlob(jobId, filePath, signal);
}

async function loadEvidence(jobId: string) {
  if (!jobId) return;
  closeEvidence();
  const request = new AbortController();
  evidenceRequest = request;
  const { signal } = request;
  evidenceJobId.value = jobId;
  evidenceLoading.value = true;
  evidenceError.value = "";
  evidenceAtts.value = [];
  evidenceFiles.value = [];
  evidenceSteps.value = [];
  try {
    let data: {
      attachments?: EvidenceAtt[];
      cases?: { name?: string; steps?: Record<string, unknown>[] }[];
    } | null = null;
    try {
      data = await api<{
        attachments?: EvidenceAtt[];
        cases?: { name?: string; steps?: Record<string, unknown>[] }[];
      }>(`/api/v1/jobs/${jobId}/result`, { signal });
    } catch {
      data = null;
    }
    if (signal.aborted) return;
    const atts = Array.isArray(data?.attachments) ? data!.attachments! : [];
    for (const a of atts) {
      const path = String(a.path || "");
      const kind = String(a.kind || "");
      if (kind === "screenshot" || /\.(png|jpe?g|gif|webp)$/i.test(path)) {
        a.previewUrl = await loadPreview(jobId, path, signal);
      }
      if (kind === "video" || /\.mp4$/i.test(path)) {
        a.videoUrl = await loadVideo(jobId, path, signal);
      }
      if (signal.aborted) return;
      if (!a.case && a.case_name) a.case = a.case_name;
    }
    evidenceAtts.value = atts;
    const steps: typeof evidenceSteps.value = [];
    for (const c of data?.cases || []) {
      for (const s of c.steps || []) {
        if (!s || typeof s !== "object") continue;
        const shot = String((s as { screenshot_path?: string }).screenshot_path || "");
        const dom = String((s as { dom_path?: string }).dom_path || "");
        const fr = String((s as { fail_reason?: string }).fail_reason || "");
        if (!shot && !dom && !fr) continue;
        steps.push({
          case: c.name,
          intent_id: String((s as { intent_id?: string }).intent_id || ""),
          fail_reason: fr,
          screenshot_path: shot,
          dom_path: dom,
          previewUrl: shot ? await loadPreview(jobId, shot, signal) : "",
        });
        if (signal.aborted) return;
      }
    }
    evidenceSteps.value = steps;

    const listed = await api<{ files?: { path?: string; kind?: string }[] }>(
      `/api/v1/jobs/${jobId}/evidence`, { signal },
    );
    if (signal.aborted) return;
    const known = new Set(
      atts.map((a) => String(a.path || "").replace(/\\/g, "/").replace(/^.*?(?:reports\/)?evidence\//, "")),
    );
    const files: EvidenceFile[] = [];
    for (const f of listed?.files || []) {
      const path = String(f.path || "");
      if (!path) continue;
      const norm = path.replace(/\\/g, "/");
      if (known.has(norm)) continue;
      const kind = String(f.kind || "");
      const item: EvidenceFile = { path, kind };
      if (kind === "image" || /\.(png|jpe?g|gif|webp)$/i.test(path)) {
        item.previewUrl = await loadPreview(jobId, path, signal);
      }
      if (kind === "video" || /\.mp4$/i.test(path)) {
        item.videoUrl = await loadVideo(jobId, path, signal);
      }
      if (signal.aborted) return;
      files.push(item);
    }
    evidenceFiles.value = files;

    if (!evidenceAtts.value.length && !steps.length && !files.length) {
      evidenceError.value = "该任务暂无步骤证据。";
    }
  } catch (e: unknown) {
    if (!signal.aborted) evidenceError.value = apiErrorMessage(e);
  } finally {
    if (evidenceRequest === request) evidenceLoading.value = false;
  }
}

function closeEvidence() {
  evidenceRequest?.abort();
  evidenceRequest = null;
  revokeEvidenceBlobs();
  evidenceJobId.value = "";
  evidenceLoading.value = false;
  evidenceError.value = "";
  evidenceAtts.value = [];
  evidenceFiles.value = [];
  evidenceSteps.value = [];
}

watch(workspaceScopeVersion, closeEvidence, { flush: "sync" });
onDeactivated(closeEvidence);
onBeforeUnmount(closeEvidence);

const VERDICT_LABEL: Record<string, string> = {
  improved: "改善",
  regressed: "回退",
  mixed: "有进有退",
  timing_only: "仅耗时变化",
  same: "持平",
};

function verdictLabel(v: string) {
  return VERDICT_LABEL[v] || v || "-";
}

function verdictTone(v: string) {
  const raw = String(v || "");
  if (raw.includes("regress") || raw === "mixed") return "regression";
  return "pass";
}

function caseRows(list: Record<string, any>[] | undefined, limit = 20) {
  return (list || []).slice(0, limit);
}

function formatDuration(ms: number) {
  if (isNaN(ms) || ms === null) return "-";
  const seconds = Math.floor((ms / 1000) % 60);
  const minutes = Math.floor((ms / (1000 * 60)) % 60);
  const hours = Math.floor((ms / (1000 * 60 * 60)) % 24);
  const hDisplay = hours > 0 ? `${hours}h ` : "";
  const mDisplay = minutes > 0 ? `${minutes}m ` : "";
  const sDisplay = seconds > 0 ? `${seconds}s` : "0s";
  return `${hDisplay}${mDisplay}${sDisplay}`;
}

function reportLabel(r: {
  job_id?: string;
  job_name?: string;
  summary?: string;
  app_build_name?: string;
  app_version_name?: string;
}) {
  const id = (r.job_id || "").slice(0, 8);
  const name = r.job_name || r.summary || "无描述";
  const ver = r.app_version_name
    ? ` · ${r.app_build_name || "app"} v${r.app_version_name}`
    : r.app_build_name
      ? ` · ${r.app_build_name}`
      : "";
  return `${id}… ${name}${ver}`;
}

const reportAppOptions = computed(() => [
  { value: "", label: "全部" },
  ...appBuilds.value.map((b) => ({
    value: b.id,
    label: `${b.name || b.filename}${b.version_name ? ` v${b.version_name}` : ""}`,
  })),
]);
const reportArtifactOptions = computed(() => [
  { value: "", label: "全部" },
  ...artifacts.value.map((a) => ({
    value: a.id,
    label: `${a.name || a.filename} · ${a.id.slice(0, 8)}…`,
  })),
]);
const reportPlatformOptions = [
  { value: "", label: "全部" },
  { value: "android", label: "Android" },
  { value: "ios", label: "iOS" },
];
const compareLeftOptions = computed(() => [
  { value: "", label: "选择基准…" },
  ...items.value
    .filter((r): r is Report & { job_id: string } => Boolean(r.job_id))
    .map((r) => ({ value: r.job_id, label: reportLabel(r) })),
]);
const compareRightOptions = computed(() => [
  { value: "", label: "选择对比…" },
  ...items.value
    .filter((r): r is Report & { job_id: string } => Boolean(r.job_id))
    .map((r) => ({ value: r.job_id, label: reportLabel(r) })),
]);

function appLabel(r: {
  app_build_name?: string;
  app_version_name?: string;
  app_build_id?: string | null;
}) {
  if (!r.app_build_id) return "-";
  const ver = r.app_version_name ? ` v${r.app_version_name}` : "";
  return `${r.app_build_name || r.app_build_id.slice(0, 8)}${ver}`;
}
</script>

<template>
  <section class="panel page-stack data-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>报告</h2>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="small" @click="activeTool = 'quality'">质量趋势</button>
        <button type="button" class="small" @click="openCompare()">报告对比</button>
      </div>
    </header>

    <div class="report-filters" role="group" aria-label="报告筛选">
      <div class="filter-field">
        <span>应用资源</span>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.app_build_id"
          aria-label="应用资源"
          :options="reportAppOptions"
        />
      </div>
      <div class="filter-field">
        <span>工程制品</span>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.artifact_id"
          aria-label="工程制品"
          :options="reportArtifactOptions"
        />
      </div>
      <div class="filter-field">
        <span>平台</span>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.platform"
          aria-label="平台"
          :options="reportPlatformOptions"
        />
      </div>
      <button v-if="hasFilters" type="button" class="linkish small" @click="clearFilters">清除筛选</button>
      <span v-if="hasLoaded && total > 0 && total <= pageSize" class="report-count">{{ total }} 条</span>
    </div>

    <div class="table-wrap">
      <table aria-label="归档报告" :aria-busy="loading">
        <thead>
          <tr>
            <th scope="col">任务</th>
            <th scope="col">应用版本</th>
            <th scope="col">工程制品</th>
            <th scope="col" class="number-cell">通过</th>
            <th scope="col" class="number-cell">失败</th>
            <th scope="col" class="number-cell">总数</th>
            <th scope="col">耗时</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && !hasLoaded">
            <td class="empty" colspan="8">正在加载报告…</td>
          </tr>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="8">
              <div v-if="error" class="empty-stack">
                <span role="alert">{{ error }}</span>
                <button type="button" class="linkish" @click="reload()">重试</button>
              </div>
              <span v-else-if="hasFilters">当前筛选无匹配报告</span>
              <div v-else class="empty-stack">
                <span>暂无归档报告</span>
                <button type="button" class="linkish" @click="activeTab = 'jobs'">查看批跑</button>
              </div>
            </td>
          </tr>
          <tr v-for="(report, index) in items" :key="report.job_id || index">
            <td>
              <button
                v-if="report.job_id"
                type="button"
                class="linkish task-link"
                :title="report.job_id"
                @click="exec.onViewReport(report.job_id)"
              >{{ report.job_name || report.job_id.slice(0, 8) }}</button>
              <span v-else>{{ report.job_name || "—" }}</span>
              <span v-if="report.summary" class="report-summary" :title="report.summary">{{ report.summary }}</span>
            </td>
            <td>{{ appLabel(report) }}</td>
            <td :title="report.artifact_id || ''">
              {{ report.artifact_name || (report.artifact_id ? report.artifact_id.slice(0, 8) + "…" : "—") }}
            </td>
            <td class="mono number-cell">{{ report.passed }}</td>
            <td class="mono number-cell" :class="{ 'text-error': report.failed > 0 }">{{ report.failed }}</td>
            <td class="mono number-cell">{{ report.total }}</td>
            <td class="mono nowrap">{{ formatDuration(report.duration_ms) }}</td>
            <td>
              <div v-if="report.job_id" class="row-actions">
                <button type="button" class="linkish small" @click="loadEvidence(report.job_id)">证据</button>
                <button type="button" class="linkish small" @click="openCompare(report.job_id)">对比</button>
              </div>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="items.length && error" class="msg bad" role="alert">{{ error }}</p>
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
      v-if="evidenceJobId"
      :title="`失败证据 · ${evidenceJobId.slice(0, 8)}`"
      variant="drawer"
      wide
      @close="closeEvidence"
    >
      <p v-if="evidenceLoading" class="evidence-muted" role="status">正在加载证据…</p>
      <p v-else-if="evidenceError" class="evidence-err" role="alert">{{ evidenceError }}</p>
      <template v-else>
        <div v-if="evidenceAtts.length" class="evidence-block">
          <div class="evidence-title">附件（{{ evidenceAtts.length }}）</div>
          <ul>
            <li v-for="(a, i) in evidenceAtts" :key="i">
              <span class="mono">{{ a.kind || "file" }}</span>
              · {{ a.case || "—" }}
              <template v-if="a.intent_id"> / {{ a.intent_id }}</template>
              <div class="path mono">{{ a.path }}</div>
              <img
                v-if="a.previewUrl"
                class="evidence-img"
                :src="a.previewUrl"
                :alt="a.path || 'screenshot'"
              />
              <video
                v-if="a.videoUrl"
                class="evidence-video"
                controls
                preload="metadata"
                :src="a.videoUrl"
              />
            </li>
          </ul>
        </div>
        <div v-if="evidenceFiles.length" class="evidence-block">
          <div class="evidence-title">证据文件（{{ evidenceFiles.length }}）</div>
          <ul>
            <li v-for="(f, i) in evidenceFiles" :key="'f' + i">
              <span class="mono">{{ f.kind || "file" }}</span>
              <div class="path mono">{{ f.path }}</div>
              <img
                v-if="f.previewUrl"
                class="evidence-img"
                :src="f.previewUrl"
                :alt="f.path || 'screenshot'"
              />
              <video
                v-if="f.videoUrl"
                class="evidence-video"
                controls
                preload="metadata"
                :src="f.videoUrl"
              />
            </li>
          </ul>
        </div>
        <div v-if="evidenceSteps.length" class="evidence-block">
          <div class="evidence-title">步骤证据（{{ evidenceSteps.length }}）</div>
          <ul>
            <li v-for="(s, i) in evidenceSteps" :key="i">
              {{ s.case || "—" }}
              <template v-if="s.intent_id"> / {{ s.intent_id }}</template>
              <template v-if="s.fail_reason"> · {{ s.fail_reason }}</template>
              <div v-if="s.screenshot_path" class="path mono">截图：{{ s.screenshot_path }}</div>
              <div v-if="s.dom_path" class="path mono">DOM：{{ s.dom_path }}</div>
              <img
                v-if="s.previewUrl"
                class="evidence-img"
                :src="s.previewUrl"
                :alt="s.screenshot_path || 'screenshot'"
              />
            </li>
          </ul>
        </div>
      </template>
      <template #actions>
        <button type="button" @click="closeEvidence">关闭</button>
      </template>
    </ApModal>

    <ApModal v-if="activeTool === 'quality'" title="质量趋势" xwide @close="closeTools">
      <JobQualityCard
        :project-id="filterProjectId || undefined"
        @goto-tab="goToQualityTarget"
      />
      <template #actions>
        <button type="button" @click="closeTools">关闭</button>
      </template>
    </ApModal>

    <ApModal
      v-if="activeTool === 'compare'"
      title="报告对比"
      xwide
      :close-on-backdrop="!comparePending"
      :close-on-esc="!comparePending"
      @close="closeTools"
    >
      <form class="comparison-grid" :aria-busy="comparePending" @submit.prevent="runComparison">
        <div class="comp-field">
          <span>基准任务</span>
          <ApSelect
            v-model="compareForm.left"
            required
            aria-label="基准任务"
            :options="compareLeftOptions"
            :disabled="comparePending"
          />
        </div>
        <div class="comp-field">
          <span>对比任务</span>
          <ApSelect
            v-model="compareForm.right"
            required
            aria-label="对比任务"
            :options="compareRightOptions"
            :disabled="comparePending"
          />
        </div>
        <button type="submit" class="primary comp-btn" :disabled="comparePending">
          {{ comparePending ? "正在对比…" : "比对" }}
        </button>
      </form>
      <p v-if="compareMsg && !compareOk" class="msg bad" role="alert">{{ compareMsg }}</p>

      <div v-if="compareResult" class="comparison-dashboard">
        <div
          class="verdict-banner"
          :class="verdictTone(compareResult.verdict)"
        >
          <span class="verdict-label">对比结论</span>
          <strong>{{ verdictLabel(compareResult.verdict) }}</strong>
          <span v-if="compareResult.same_app_build === false" class="verdict-hint">跨应用版本</span>
          <span v-else-if="compareResult.same_artifact === false" class="verdict-hint">跨工程制品</span>
        </div>

        <div class="table-wrap compact">
          <table>
            <thead>
              <tr>
                <th>对比项</th>
                <th>基准</th>
                <th>对比</th>
                <th>差异</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>任务</td>
                <td class="mono small">
                  {{ compareResult.left.job_name }} ({{ compareResult.left.job_id.slice(0, 8) }})
                </td>
                <td class="mono small">
                  {{ compareResult.right.job_name }} ({{ compareResult.right.job_id.slice(0, 8) }})
                </td>
                <td class="mono">-</td>
              </tr>
              <tr>
                <td>应用资源</td>
                <td class="small">
                  {{ compareResult.left.app_build_name || "-" }}{{ compareResult.left.app_version_name ? ` v${compareResult.left.app_version_name}` : "" }}
                </td>
                <td class="small">
                  {{ compareResult.right.app_build_name || "-" }}{{ compareResult.right.app_version_name ? ` v${compareResult.right.app_version_name}` : "" }}
                </td>
                <td class="mono">{{ compareResult.same_app_build ? "同版本" : "不同" }}</td>
              </tr>
              <tr>
                <td>工程制品</td>
                <td class="small">
                  {{ compareResult.left.artifact_name || compareResult.left.artifact_id || "-" }}
                </td>
                <td class="small">
                  {{ compareResult.right.artifact_name || compareResult.right.artifact_id || "-" }}
                </td>
                <td class="mono">{{ compareResult.same_artifact ? "同制品" : "不同" }}</td>
              </tr>
              <tr>
                <td>通过</td>
                <td><span class="text-success font-semibold">{{ compareResult.left.passed }}</span></td>
                <td><span class="text-success font-semibold">{{ compareResult.right.passed }}</span></td>
                <td :class="compareResult.delta.passed >= 0 ? 'text-success' : 'text-error'">
                  {{ compareResult.delta.passed >= 0 ? "+" : "" }}{{ compareResult.delta.passed }}
                </td>
              </tr>
              <tr>
                <td>失败</td>
                <td><span class="text-error font-semibold">{{ compareResult.left.failed }}</span></td>
                <td><span class="text-error font-semibold">{{ compareResult.right.failed }}</span></td>
                <td :class="compareResult.delta.failed <= 0 ? 'text-success' : 'text-error'">
                  {{ compareResult.delta.failed > 0 ? "+" : "" }}{{ compareResult.delta.failed }}
                </td>
              </tr>
              <tr>
                <td>总数</td>
                <td>{{ compareResult.left.total }}</td>
                <td>{{ compareResult.right.total }}</td>
                <td>{{ compareResult.delta.total > 0 ? "+" : "" }}{{ compareResult.delta.total }}</td>
              </tr>
              <tr>
                <td>耗时</td>
                <td>{{ formatDuration(compareResult.left.duration_ms) }}</td>
                <td>{{ formatDuration(compareResult.right.duration_ms) }}</td>
                <td :class="compareResult.delta.duration_ms <= 0 ? 'text-success' : 'text-error'">
                  {{ compareResult.delta.duration_ms > 0 ? "+" : "" }}{{ formatDuration(compareResult.delta.duration_ms) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="compareResult.cases && !compareResult.cases.available" class="case-diff-hint">
          两侧缺少 result.json，仅能对比汇总数字
        </p>
        <div v-else-if="compareResult.cases" class="case-diff">
          <div class="case-diff-grid">
            <div class="case-diff-col">
              <h4>新增失败（{{ compareResult.cases.counts?.new_fail || 0 }}）</h4>
              <ul v-if="(compareResult.cases.new_fail || []).length">
                <li v-for="(row, i) in caseRows(compareResult.cases.new_fail)" :key="'nf-'+i">
                  <span class="name">{{ row.name || row.key }}</span>
                  <span v-if="row.fail_class_label" class="why">{{ row.fail_class_label }}</span>
                </li>
              </ul>
            </div>
            <div class="case-diff-col">
              <h4>已修复（{{ compareResult.cases.counts?.fixed || 0 }}）</h4>
              <ul v-if="(compareResult.cases.fixed || []).length">
                <li v-for="(row, i) in caseRows(compareResult.cases.fixed)" :key="'fx-'+i">
                  <span class="name">{{ row.name || row.key }}</span>
                </li>
              </ul>
            </div>
            <div class="case-diff-col">
              <h4>仍失败（{{ compareResult.cases.counts?.still_fail || 0 }}）</h4>
              <ul v-if="(compareResult.cases.still_fail || []).length">
                <li v-for="(row, i) in caseRows(compareResult.cases.still_fail)" :key="'sf-'+i">
                  <span class="name">{{ row.name || row.key }}</span>
                  <span v-if="row.fail_class_label" class="why">{{ row.fail_class_label }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
      <template #actions>
        <button type="button" :disabled="comparePending" @click="closeTools">关闭</button>
      </template>
    </ApModal>
  </section>
</template>

<style scoped>
.report-filters {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
}

.filter-field {
  display: grid;
  gap: var(--space-1);
  flex: 0 1 11rem;
  min-width: 0;
}

.filter-field > span,
.report-count {
  color: var(--muted);
  font-size: 0.82rem;
}

.report-count {
  align-self: center;
  margin-left: auto;
  white-space: nowrap;
}

.task-link {
  width: auto;
  font-weight: 600;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}

.report-summary {
  display: block;
  max-width: 18rem;
  margin-top: var(--space-1);
  color: var(--muted);
  font-size: 0.8rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.number-cell {
  text-align: right;
}

.nowrap {
  white-space: nowrap;
}

.evidence-img {
  display: block;
  max-width: min(100%, 480px);
  margin-top: 0.4rem;
  border: 1px solid var(--line-soft);
  border-radius: 4px;
}
.evidence-video {
  display: block;
  max-width: min(100%, 560px);
  margin-top: 0.4rem;
  border: 1px solid var(--line-soft);
  border-radius: 4px;
  background: #000;
}
.evidence-block {
  margin-top: 0.65rem;
}
.evidence-title {
  font-size: 0.78rem;
  font-weight: 600;
  opacity: 0.75;
  margin-bottom: 0.35rem;
}
.evidence-block ul {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 0.85rem;
}
.evidence-block li {
  margin-bottom: 0.45rem;
}
.path {
  font-size: 0.75rem;
  opacity: 0.8;
  word-break: break-all;
}
.evidence-muted {
  margin: 0.5rem 0 0;
  font-size: 0.8rem;
  opacity: 0.65;
}
.evidence-err {
  color: var(--danger-soft-fg);
  font-size: 0.85rem;
}
.comparison-grid {
  display: grid;
  grid-template-columns: minmax(12rem, 1fr) minmax(12rem, 1fr) auto;
  gap: 0.75rem 1rem;
  align-items: end;
  max-width: 52rem;
}

.comp-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.comp-field > span {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
}

.comp-field .ap-select {
  width: 100%;
}

.comp-btn {
  height: 38px;
  white-space: nowrap;
  padding: 0 1.25rem;
}

.comparison-dashboard {
  margin-top: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border-top: 1px solid var(--line);
  padding-top: 1.25rem;
}

.verdict-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  font-size: var(--font-size-body);
}

.verdict-banner.regression {
  color: var(--danger-soft-fg);
}

.verdict-banner.pass {
  color: var(--ok-soft-fg);
}

.verdict-label,
.verdict-hint {
  color: var(--muted);
}

.case-diff-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
}

.case-diff {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.case-diff-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.75rem;
}

.case-diff-col h4 {
  margin: 0 0 0.4rem;
  font-size: 0.78rem;
  color: var(--muted);
}

.case-diff-col ul {
  margin: 0;
  padding-left: 1.05rem;
  font-size: 0.82rem;
}

.case-diff-col li {
  margin-bottom: 0.3rem;
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}

.case-diff-col .why {
  color: var(--muted);
  font-size: 0.72rem;
  flex-shrink: 0;
}

.text-success { color: var(--ok); }
.text-error { color: var(--bad); }
.font-semibold { font-weight: 600; }

.table-wrap.compact th,
.table-wrap.compact td {
  padding: 0.55rem 0.75rem;
}

@media (max-width: 768px) {
  .comparison-grid {
    grid-template-columns: 1fr;
  }
  .comp-btn {
    width: 100%;
  }
}
</style>
