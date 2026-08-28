<script setup lang="ts">
defineOptions({ name: "ReportsPanel" });

import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api, apiErrorMessage, sessionFetch, type Report } from "../api";
import { listReportsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../stores/projectsStore";
import { useShellStore } from "../stores/shellStore";
import { usePagedList } from "../composables/usePagedList";
import { useExecStore } from "../stores/execution";
import DataPager from "./common/DataPager.vue";
import JobQualityCard from "./JobQualityCard.vue";
import ApSelect from "./common/ApSelect.vue";

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
  resetSources: [() => filterProjectId.value],
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

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

watch(reportsListVersion, () => void reload(false));
void reload(true);

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

async function loadMediaBlob(jobId: string, filePath: string): Promise<string> {
  if (!filePath) return "";
  try {
    const res = await sessionFetch(evidenceApiPath(jobId, filePath));
    if (!res.ok) return "";
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    blobUrls.push(url);
    return url;
  } catch {
    return "";
  }
}

async function loadPreview(jobId: string, filePath: string): Promise<string> {
  if (!filePath || !/\.(png|jpe?g|gif|webp)$/i.test(filePath)) return "";
  return loadMediaBlob(jobId, filePath);
}

async function loadVideo(jobId: string, filePath: string): Promise<string> {
  if (!filePath || !/\.mp4$/i.test(filePath)) return "";
  return loadMediaBlob(jobId, filePath);
}

async function loadEvidence(jobId: string) {
  if (!jobId) return;
  revokeEvidenceBlobs();
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
      }>(`/api/v1/jobs/${jobId}/result`);
    } catch {
      data = null;
    }
    const atts = Array.isArray(data?.attachments) ? data!.attachments! : [];
    for (const a of atts) {
      const path = String(a.path || "");
      const kind = String(a.kind || "");
      if (kind === "screenshot" || /\.(png|jpe?g|gif|webp)$/i.test(path)) {
        a.previewUrl = await loadPreview(jobId, path);
      }
      if (kind === "video" || /\.mp4$/i.test(path)) {
        a.videoUrl = await loadVideo(jobId, path);
      }
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
          previewUrl: shot ? await loadPreview(jobId, shot) : "",
        });
      }
    }
    evidenceSteps.value = steps;

    const listed = await api<{ files?: { path?: string; kind?: string }[] }>(
      `/api/v1/jobs/${jobId}/evidence`,
    );
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
        item.previewUrl = await loadPreview(jobId, path);
      }
      if (kind === "video" || /\.mp4$/i.test(path)) {
        item.videoUrl = await loadVideo(jobId, path);
      }
      files.push(item);
    }
    evidenceFiles.value = files;

    if (!evidenceAtts.value.length && !steps.length && !files.length) {
      evidenceError.value = "该任务暂无步骤证据（需执行端上传完整结果或 evidence.zip）";
    }
  } catch (e: unknown) {
    evidenceError.value = apiErrorMessage(e);
  } finally {
    evidenceLoading.value = false;
  }
}

function closeEvidence() {
  revokeEvidenceBlobs();
  evidenceJobId.value = "";
  evidenceError.value = "";
  evidenceAtts.value = [];
  evidenceFiles.value = [];
  evidenceSteps.value = [];
}

onBeforeUnmount(() => {
  revokeEvidenceBlobs();
});

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
  { value: "android", label: "android" },
  { value: "ios", label: "ios" },
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
  <section class="panel page-stack">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>报告</h2>
        <p class="lede">查看任务报告和失败步骤，也可对比多次结果。</p>
      </div>
      <div v-if="total > 0" class="page-hero-actions">
        <div class="archive-count" aria-label="报告总数">
          <span class="archive-count-n">{{ total }}</span>
          <span class="archive-count-l">条归档</span>
        </div>
      </div>
    </header>

    <!-- Primary: archive -->
    <div class="panel-filter-bar" aria-label="报告筛选">
      <div class="filter-field">
        <label>应用资源</label>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.app_build_id"
          aria-label="应用资源"
          :options="reportAppOptions"
        />
      </div>
      <div class="filter-field">
        <label>工程制品</label>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.artifact_id"
          aria-label="工程制品"
          :options="reportArtifactOptions"
        />
      </div>
      <div class="filter-field">
        <label>平台</label>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="reportFilter.platform"
          aria-label="平台"
          :options="reportPlatformOptions"
        />
      </div>
    </div>

    <div class="archive-block">
      <div class="archive-head">
        <h3 class="section-title">归档列表</h3>
        <p class="archive-hint">点击「打开报告」查看完整 HTML；「证据」查看失败截图/录像索引。</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>应用版本</th>
              <th>工程制品</th>
              <th>通过</th>
              <th>失败</th>
              <th>总数</th>
              <th>耗时</th>
              <th>摘要</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!items.length && hasLoaded">
              <td class="empty" colspan="9">
                <div class="empty-stack">
                  <span>还没有报告</span>
                  <span>任务跑完后会自动出现在这里</span>
                </div>
              </td>
            </tr>
            <tr v-for="(r, i) in items" :key="r.job_id || i">
              <td class="mono">
                <button
                  type="button"
                  class="small pick-btn"
                  :title="'选入对比：' + (r.job_name || r.job_id)"
                  @click="exec.pickCompare(r.job_id || '')"
                >
                  {{ (r.job_id || "").slice(0, 8) }}…
                </button>
                <div class="job-name-hint">{{ r.job_name || "" }}</div>
              </td>
              <td class="version-cell" :title="r.app_build_id || ''">{{ appLabel(r) }}</td>
              <td class="version-cell" :title="r.artifact_id || ''">
                {{ r.artifact_name || (r.artifact_id ? r.artifact_id.slice(0, 8) + "…" : "-") }}
              </td>
              <td><span class="badge success">{{ r.passed }}</span></td>
              <td>
                <span class="badge" :class="r.failed > 0 ? 'error' : 'secondary'">{{ r.failed }}</span>
              </td>
              <td><span class="total-count-lbl">{{ r.total }}</span></td>
              <td class="mono">{{ formatDuration(r.duration_ms) }}</td>
              <td class="summary-cell" :title="r.summary">{{ r.summary || "-" }}</td>
              <td class="ops-cell">
                <button type="button" class="primary small" @click="exec.onViewReport(r.job_id || '')">
                  打开报告
                </button>
                <button type="button" class="small" @click="loadEvidence(r.job_id || '')">证据</button>
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
    </div>

    <div v-if="evidenceJobId" class="evidence-drawer" role="dialog" aria-label="失败证据">
      <div class="evidence-head">
        <h3>失败证据 · {{ evidenceJobId.slice(0, 8) }}…</h3>
        <button type="button" class="small" @click="closeEvidence">关闭</button>
      </div>
      <p v-if="evidenceLoading" class="evidence-muted">正在加载证据…</p>
      <p v-else-if="evidenceError" class="evidence-err">{{ evidenceError }}</p>
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
        <p class="evidence-muted">
          截图/录像需 Runner 上传 evidence.zip 后可预览；未上传时仅显示路径索引。
        </p>
      </template>
    </div>

    <!-- Secondary: quality + compare -->
    <details class="secondary-tools">
      <summary>
        <div>
          <div class="secondary-title">分析与对比</div>
          <div class="secondary-desc">任务质量趋势、两份报告通过率与失败差异（次要）</div>
        </div>
        <span class="secondary-toggle" data-closed>展开</span>
        <span class="secondary-toggle" data-open>收起</span>
      </summary>
      <div class="secondary-body">
        <JobQualityCard
          class="reports-quality"
          :project-id="filterProjectId || undefined"
          @goto-tab="(tab) => (activeTab = tab)"
        />

        <div class="nested-form-card">
          <h3 class="comparison-title">报告对比</h3>
          <form class="comparison-form" @submit.prevent="exec.onCompareReports">
            <div class="comparison-grid">
              <div class="comp-field">
                <label>基准任务 *</label>
                <ApSelect
                  v-model="compareForm.left"
                  required
                  aria-label="基准任务"
                  :options="compareLeftOptions"
                />
              </div>
              <div class="comp-field">
                <label>对比任务 *</label>
                <ApSelect
                  v-model="compareForm.right"
                  required
                  aria-label="对比任务"
                  :options="compareRightOptions"
                />
              </div>
              <button type="submit" class="primary comp-btn">比对</button>
            </div>
          </form>
          <p v-if="compareMsg" class="msg" :class="compareOk ? 'ok' : 'bad'">{{ compareMsg }}</p>

          <div v-if="compareResult" class="comparison-dashboard">
            <div
              class="verdict-banner"
              :class="verdictTone(compareResult.verdict)"
            >
              <div class="verdict-details">
                <span class="verdict-label">结论</span>
                <span class="verdict-value">{{ verdictLabel(compareResult.verdict) }}</span>
                <span v-if="compareResult.same_app_build === false" class="verdict-hint">跨应用版本对比</span>
                <span v-else-if="compareResult.same_artifact === false" class="verdict-hint">跨工程制品对比</span>
              </div>
            </div>

            <div class="comparison-stats-row">
              <div class="comparison-stat-card">
                <span class="stat-label">失败变化</span>
                <span class="stat-val" :class="compareResult.delta.failed > 0 ? 'text-error' : 'text-success'">
                  {{ compareResult.delta.failed > 0 ? "+" : "" }}{{ compareResult.delta.failed }}
                </span>
              </div>
              <div class="comparison-stat-card">
                <span class="stat-label">通过变化</span>
                <span class="stat-val" :class="compareResult.delta.passed >= 0 ? 'text-success' : 'text-error'">
                  {{ compareResult.delta.passed > 0 ? "+" : "" }}{{ compareResult.delta.passed }}
                </span>
              </div>
              <div class="comparison-stat-card">
                <span class="stat-label">耗时变化</span>
                <span class="stat-val text-accent">
                  {{ compareResult.delta.duration_ms > 0 ? "+" : "" }}{{ formatDuration(compareResult.delta.duration_ms) }}
                </span>
              </div>
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
              <div class="comparison-stats-row case-diff-stats">
                <div class="comparison-stat-card">
                  <span class="stat-label">新增失败</span>
                  <span class="stat-val text-error">{{ compareResult.cases.counts?.new_fail || 0 }}</span>
                </div>
                <div class="comparison-stat-card">
                  <span class="stat-label">已修复</span>
                  <span class="stat-val text-success">{{ compareResult.cases.counts?.fixed || 0 }}</span>
                </div>
                <div class="comparison-stat-card">
                  <span class="stat-label">仍失败</span>
                  <span class="stat-val">{{ compareResult.cases.counts?.still_fail || 0 }}</span>
                </div>
              </div>
              <div class="case-diff-grid">
                <div v-if="(compareResult.cases.new_fail || []).length" class="case-diff-col">
                  <h4>新增失败</h4>
                  <ul>
                    <li v-for="(row, i) in caseRows(compareResult.cases.new_fail)" :key="'nf-'+i">
                      <span class="name">{{ row.name || row.key }}</span>
                      <span v-if="row.fail_class_label" class="why">{{ row.fail_class_label }}</span>
                    </li>
                  </ul>
                </div>
                <div v-if="(compareResult.cases.fixed || []).length" class="case-diff-col">
                  <h4>已修复</h4>
                  <ul>
                    <li v-for="(row, i) in caseRows(compareResult.cases.fixed)" :key="'fx-'+i">
                      <span class="name">{{ row.name || row.key }}</span>
                    </li>
                  </ul>
                </div>
                <div v-if="(compareResult.cases.still_fail || []).length" class="case-diff-col">
                  <h4>仍失败</h4>
                  <ul>
                    <li v-for="(row, i) in caseRows(compareResult.cases.still_fail)" :key="'sf-'+i">
                      <span class="name">{{ row.name || row.key }}</span>
                      <span v-if="row.fail_class_label" class="why">{{ row.fail_class_label }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.archive-count {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.1;
}
.archive-count-n {
  font-size: 1.5rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.archive-count-l {
  font-size: 0.72rem;
  color: var(--muted);
}
.archive-block {
  margin-bottom: 1.25rem;
}
.archive-head {
  margin-bottom: 0.5rem;
}
.archive-head .section-title {
  margin: 0 0 0.25rem !important;
}
.archive-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
}
.secondary-tools {
  margin-top: 0.5rem;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  background: var(--surface-soft);
}
.secondary-tools > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1.1rem;
  user-select: none;
}
.secondary-tools > summary::-webkit-details-marker {
  display: none;
}
.secondary-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
}
.secondary-desc {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.15rem;
}
.secondary-toggle {
  font-size: 0.75rem;
  color: var(--muted);
  flex-shrink: 0;
}
.secondary-tools[open] > summary .secondary-toggle[data-closed] {
  display: none;
}
.secondary-tools:not([open]) > summary .secondary-toggle[data-open] {
  display: none;
}
.secondary-body {
  padding: 0 1.1rem 1.1rem;
  border-top: 1px solid var(--line-soft);
  padding-top: 1rem;
}
.ops-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.evidence-drawer {
  margin-top: 1rem;
  padding: 1rem 1.1rem;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  background: var(--surface-soft);
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
.evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}
.evidence-head h3 {
  margin: 0;
  font-size: 0.95rem;
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
.nested-form-card {
  background-color: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 1.25rem;
  margin-bottom: 0;
  width: 100%;
}

.comparison-title {
  margin: 0 0 1rem !important;
  font-size: 0.95rem !important;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text);
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.5rem;
}

.title-svg {
  color: var(--accent-text);
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

.comp-field label {
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

.section-title {
  margin: 1.5rem 0 0.5rem !important;
  font-size: 1rem !important;
  font-weight: 700;
  color: var(--text);
}

.comparison-dashboard {
  margin-top: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border-top: 1px dashed var(--line);
  padding-top: 1.25rem;
}

.verdict-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1.25rem;
  border-radius: 8px;
  border: 1px solid transparent;
}

.verdict-banner.regression {
  background-color: var(--danger-soft-bg);
  border-color: var(--danger-soft-border);
  color: var(--danger-soft-fg);
}

.verdict-banner.pass {
  background-color: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
  color: var(--ok-soft-fg);
}

.verdict-details {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.verdict-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.8;
}

.verdict-value {
  font-size: 1.1rem;
  font-weight: 700;
}

.verdict-hint {
  font-size: 0.78rem;
  opacity: 0.85;
}

.comparison-stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
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

.comparison-stat-card {
  background-color: var(--chip-bg);
  border: 1px solid var(--line);
  padding: 0.75rem 1rem;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.stat-label {
  font-size: 0.72rem;
  color: var(--muted);
  margin-bottom: 0.25rem;
}

.stat-val {
  font-size: 1.35rem;
  font-weight: 800;
}

.badge {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  border: 1px solid transparent;
}

.badge.success {
  background-color: var(--ok-soft-bg);
  color: var(--ok-soft-fg);
}

.badge.error {
  background-color: var(--danger-soft-bg);
  color: var(--danger-soft-fg);
}

.badge.secondary {
  background-color: var(--control-bg);
  color: var(--muted);
}

.total-count-lbl {
  font-weight: 600;
}

.summary-cell,
.version-cell {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 0.82rem;
}

.job-name-hint {
  font-size: 0.72rem;
  color: var(--muted);
  margin-top: 0.15rem;
  max-width: 7rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pick-btn {
  background-color: var(--indigo-soft-bg);
  border-color: var(--indigo-soft-border);
  color: var(--indigo-soft-fg);
  font-weight: 700;
}

.pick-btn:hover {
  background-color: var(--indigo-soft-fg);
  border-color: transparent;
  color: var(--on-accent);
}

.text-success { color: var(--ok); }
.text-error { color: var(--bad); }
.text-accent { color: var(--accent-text); }
.font-semibold { font-weight: 600; }

.table-wrap.compact th,
.table-wrap.compact td {
  padding: 0.55rem 0.75rem;
}

.reports-quality {
  margin: 0 0 1rem;
}
.secondary-body .reports-quality {
  margin-bottom: 1rem;
}

@media (max-width: 768px) {
  .comparison-grid {
    grid-template-columns: 1fr;
  }
  .comp-btn {
    width: 100%;
  }
  .comparison-stats-row {
    grid-template-columns: 1fr;
  }
}
</style>
