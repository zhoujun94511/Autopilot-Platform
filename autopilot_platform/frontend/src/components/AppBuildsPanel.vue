<script setup lang="ts">
defineOptions({ name: "AppBuildsPanel" });

import { storeToRefs } from "pinia";
import { computed, nextTick, ref, watch } from "vue";
import type { AppBuild } from "../api";
import { listAppBuildsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import ApSelect from "./common/ApSelect.vue";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const {
  appBuildsVersion,
  appBuildUploadName,
  appBuildUploadFile,
  appBuildMsg,
  appBuildMsgOk,
} = storeToRefs(exec);
const caps = useCapabilities();
const canUpload = computed(() => Boolean(caps.canEditProject));
const search = ref("");
const platformFilter = ref("");
const fileInput = ref<HTMLInputElement | null>(null);
const uploadHighlight = ref(false);
let highlightTimer: ReturnType<typeof setTimeout> | null = null;

const list = usePagedList<AppBuild>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listAppBuildsPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
      platform: platformFilter.value.trim() || undefined,
    }),
  resetSources: [() => filterProjectId.value],
  filterSources: [platformFilter],
  isUnfiltered: () => !platformFilter.value.trim(),
});

const { items: pagedItems, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

watch(appBuildsVersion, () => void reload(false));
void reload(true);

function formatBytes(bytes: number, decimals = 2) {
  if (!bytes) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

const filteredBuilds = computed(() => {
  const q = search.value.trim().toLowerCase();
  return pagedItems.value.filter((b) => {
    if (!q) return true;
    const hay = [b.id, b.name, b.filename, b.platform, b.version_name, b.package_id, b.uploaded_by, b.project_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
});

const selectedFileName = computed(() => appBuildUploadFile.value?.name || "");

function pulseUploadCard() {
  uploadHighlight.value = true;
  if (highlightTimer) clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => {
    uploadHighlight.value = false;
    highlightTimer = null;
  }, 1600);
}

async function startUpload() {
  pulseUploadCard();
  document.getElementById("app-build-upload")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  await nextTick();
  fileInput.value?.click();
}

function onFilePicked(ev: Event) {
  exec.onAppBuildFileChange(ev);
}

async function submitUpload(ev: Event) {
  await exec.onUploadAppBuild(ev);
  if (appBuildMsgOk.value && fileInput.value) {
    fileInput.value.value = "";
  }
}
</script>

<template>
  <section class="panel page-stack">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>应用资源</h2>
        <p class="lede">管理安装包（apk / xapk / ipa）。</p>
      </div>
      <div class="page-hero-actions">
        <label class="toolbar-search">
          <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input v-model="search" type="search" placeholder="搜索名称 / 文件 / 版本…" />
        </label>
        <ApSelect
          class="toolbar-select"
          size="toolbar"
          v-model="platformFilter"
          aria-label="平台筛选"
          :options="[
            { value: '', label: '平台：全部' },
            { value: 'android', label: 'android' },
            { value: 'ios', label: 'ios' },
          ]"
        />
        <button
          v-if="canUpload"
          type="button"
          class="primary small"
          title="选择 apk / ipa 并上传"
          @click="startUpload"
        >
          上传安装包
        </button>
        <button
          v-if="caps.canOps"
          type="button"
          class="danger small"
          title="按保留天数清理过期安装包"
          @click="exec.onPurgeAppBuilds"
        >
          清理超期
        </button>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="上传安装包" />

    <div
      v-if="canUpload"
      id="app-build-upload"
      class="upload-section-card"
      :class="{ highlight: uploadHighlight }"
    >
      <h3 class="upload-title">
        <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" class="title-svg">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        上传 apk / ipa / xapk（与工程制品分离，按版本管理）
      </h3>
      <form class="upload-form" @submit.prevent="submitUpload">
        <div class="upload-grid">
          <div class="input-field">
            <label>显示名称</label>
            <input v-model="appBuildUploadName" placeholder="例如: Demo_1.2.0" />
          </div>
          <div class="input-field flex-two">
            <label>安装包 *</label>
            <div class="file-picker-wrapper">
              <input
                ref="fileInput"
                type="file"
                accept=".apk,.apex,.xapk,.ipa,application/vnd.android.package-archive"
                required
                class="real-file-input"
                @change="onFilePicked"
              />
              <span v-if="selectedFileName" class="file-picked-name" :title="selectedFileName">
                已选：{{ selectedFileName }}
              </span>
            </div>
          </div>
          <button type="submit" class="primary upload-btn" :disabled="!appBuildUploadFile">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            开始上传
          </button>
        </div>
      </form>
      <p v-if="appBuildMsg" class="msg" :class="appBuildMsgOk ? 'ok' : 'bad'">
        {{ appBuildMsg }}
      </p>
    </div>

    <h3 class="list-title">列表</h3>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>资源 ID</th>
            <th>名称</th>
            <th>平台</th>
            <th>包名</th>
            <th>文件</th>
            <th>版本</th>
            <th>大小</th>
            <th>上传者</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!filteredBuilds.length && hasLoaded">
            <td class="empty" colspan="9">
              {{
                total
                  ? "无匹配应用资源，请调整搜索或平台筛选"
                  : "还没有安装包"
              }}
            </td>
          </tr>
          <tr v-for="b in filteredBuilds" :key="b.id">
            <td class="mono">
              <button
                type="button"
                class="small art-id-btn"
                title="选中后，创建任务时可直接用这个安装包"
                @click="exec.selectAppBuild(b.id)"
              >
                {{ b.id.slice(0, 8) }}…
              </button>
            </td>
            <td class="art-name-cell">{{ b.name || "-" }}</td>
            <td>{{ b.platform || "-" }}</td>
            <td class="mono" :title="b.package_id || ''">{{ b.package_id || "-" }}</td>
            <td class="mono font-semibold">{{ b.filename }}</td>
            <td class="mono">
              {{ b.version_name || "-" }}
              <span v-if="b.version_code" class="ver-code">({{ b.version_code }})</span>
            </td>
            <td>{{ formatBytes(b.size_bytes) }}</td>
            <td><span class="user-pill">{{ b.uploaded_by || "-" }}</span></td>
            <td>
              <div class="action-btn-group">
                <button
                  type="button"
                  class="small"
                  title="重命名显示名称"
                  @click="exec.onRenameAppBuild(b.id, b.name)"
                >
                  重命名
                </button>
                <button
                  type="button"
                  class="small"
                  title="分享这个安装包"
                  @click="ops.selectAppBuildForShare(b.id)"
                >
                  分享
                </button>
                <button
                  type="button"
                  class="small danger"
                  title="删除此应用资源"
                  @click="exec.onDeleteAppBuild(b.id)"
                >
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
  </section>
</template>

<style scoped>
.upload-section-card {
  background-color: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 1.25rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.upload-section-card.highlight {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--brand-soft, rgba(21, 101, 192, 0.18));
}

.upload-title {
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

.upload-grid {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
  width: 100%;
}

.input-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex: 1;
}

.input-field label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.file-picker-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
}

.real-file-input {
  cursor: pointer;
  padding: 0.4rem;
  width: 100%;
}

.file-picked-name {
  font-size: 0.75rem;
  color: var(--muted);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-btn {
  height: 38px;
  padding: 0 1.25rem;
}

.list-title {
  margin-top: 1.5rem;
}

.art-id-btn {
  background-color: var(--indigo-soft-bg);
  border-color: var(--indigo-soft-border);
  color: var(--indigo-soft-fg);
  font-weight: 700;
}

.art-id-btn:hover {
  background-color: var(--indigo-soft-fg);
  border-color: transparent;
  color: var(--on-accent);
}

.art-name-cell {
  font-weight: 600;
  color: var(--text);
}

.user-pill {
  font-size: 0.75rem;
  background-color: var(--control-bg);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  border: 1px solid var(--line);
  color: var(--muted);
}

.action-btn-group {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.flex-two {
  flex: 2;
}

.ver-code {
  color: var(--muted);
  font-size: 0.85em;
}

.font-semibold {
  font-weight: 600;
}

@media (max-width: 768px) {
  .upload-grid {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
