<script setup lang="ts">
defineOptions({ name: "AppBuildsPanel" });

import { storeToRefs } from "pinia";
import { computed, onDeactivated, ref, watch } from "vue";
import type { AppBuild } from "../api";
import { listAppBuildsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { workspaceScopeVersion } from "../composables/mcProjectsState";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import ApSelect from "./common/ApSelect.vue";
import ApModal from "./ApModal.vue";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const {
  appBuildsVersion,
  appBuildUploadName,
  appBuildUploadFile,
  uploadingAppBuild,
  appBuildMsg,
  appBuildMsgOk,
  form,
} = storeToRefs(exec);
const caps = useCapabilities();
const canUpload = computed(() => Boolean(caps.canEditProject));
const search = ref("");
const platformFilter = ref("");
const uploadOpen = ref(false);
const platformLabels: Record<string, string> = { android: "Android", ios: "iOS" };

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
  resetSources: [workspaceScopeVersion],
  filterSources: [platformFilter],
  isUnfiltered: () => !platformFilter.value.trim(),
});

const { items: pagedItems, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

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

function clearBuildFilter() {
  search.value = "";
  platformFilter.value = "";
}

function openUpload() {
  if (uploadingAppBuild.value || !canUpload.value) return;
  appBuildMsg.value = "";
  uploadOpen.value = true;
}

function resetUpload() {
  uploadOpen.value = false;
  appBuildUploadFile.value = null;
}

function closeUpload() {
  if (!uploadingAppBuild.value) resetUpload();
}

async function submitUpload(ev: Event) {
  if (await exec.onUploadAppBuild(ev)) closeUpload();
}

onDeactivated(resetUpload);
watch(workspaceScopeVersion, resetUpload);
</script>

<template>
  <section class="panel page-stack data-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>应用资源</h2>
      </div>
      <div class="page-hero-actions">
        <button
          v-if="canUpload"
          type="button"
          class="primary small"
          :disabled="uploadingAppBuild"
          @click="openUpload"
        >上传安装包</button>
        <details v-if="caps.canOps" class="action-menu">
          <summary class="small">更多</summary>
          <div class="action-menu-panel">
            <button type="button" class="danger-item" @click="exec.onPurgeAppBuilds">
              清理过期安装包
            </button>
          </div>
        </details>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="上传安装包" />
    <div class="list-toolbar" aria-label="应用资源筛选">
      <input
        v-model="search"
        type="search"
        aria-label="搜索本页应用资源"
        placeholder="搜索本页应用资源"
      />
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        v-model="platformFilter"
        aria-label="平台筛选"
        :options="[
          { value: '', label: '全部平台' },
          { value: 'android', label: 'Android' },
          { value: 'ios', label: 'iOS' },
        ]"
      />
      <button
        v-if="search.trim() || platformFilter"
        type="button"
        class="linkish"
        @click="clearBuildFilter"
      >清除筛选</button>
    </div>
    <p v-if="appBuildMsg && appBuildMsgOk && !uploadOpen" class="msg ok" role="status">
      {{ appBuildMsg }}
    </p>

    <div class="table-wrap">
      <table aria-label="应用资源" :aria-busy="loading">
        <thead>
          <tr>
            <th scope="col">应用包</th>
            <th scope="col">平台</th>
            <th scope="col">版本</th>
            <th scope="col">大小</th>
            <th scope="col">上传者</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!filteredBuilds.length && !hasLoaded">
            <td class="empty" colspan="6">正在加载应用资源…</td>
          </tr>
          <tr v-if="!filteredBuilds.length && hasLoaded">
            <td class="empty" colspan="6">
              <div v-if="error" class="empty-stack">
                <span role="alert">{{ error }}</span>
                <button type="button" class="linkish" @click="reload()">重试</button>
              </div>
              <span v-else-if="search.trim() || platformFilter">当前筛选无匹配的应用资源</span>
              <span v-else>暂无安装包</span>
            </td>
          </tr>
          <tr v-for="build in filteredBuilds" :key="build.id">
            <td>
              <span class="entry-name">{{ build.name || build.filename }}</span>
              <span v-if="build.name && build.name !== build.filename" class="entry-meta mono">{{ build.filename }}</span>
              <span class="entry-meta mono" :title="build.id">
                <template v-if="build.package_id">{{ build.package_id }} · </template>{{ build.id.slice(0, 8) }}…
              </span>
            </td>
            <td>{{ platformLabels[build.platform] || build.platform || "—" }}</td>
            <td class="mono nowrap">
              {{ build.version_name || "—" }}
              <span v-if="build.version_code" class="version-code">({{ build.version_code }})</span>
            </td>
            <td class="mono nowrap">{{ formatBytes(build.size_bytes) }}</td>
            <td>{{ build.uploaded_by || "—" }}</td>
            <td>
              <div class="row-actions">
                <button
                  type="button"
                  class="linkish small"
                  :title="build.id"
                  :aria-pressed="form.app_build_id === build.id"
                  @click="exec.selectAppBuild(build.id)"
                >{{ form.app_build_id === build.id ? "已选用" : "选用" }}</button>
                <button type="button" class="linkish small" @click="exec.onRenameAppBuild(build.id, build.name)">重命名</button>
                <button type="button" class="linkish small" @click="ops.selectAppBuildForShare(build.id)">分享</button>
                <button type="button" class="linkish small danger-item" @click="exec.onDeleteAppBuild(build.id)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="filteredBuilds.length && error" class="msg bad" role="alert">{{ error }}</p>
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
      v-if="uploadOpen"
      title="上传安装包"
      wide
      :close-on-backdrop="!uploadingAppBuild"
      :close-on-esc="!uploadingAppBuild"
      @close="closeUpload"
    >
      <form class="upload-form" :aria-busy="uploadingAppBuild" @submit.prevent="submitUpload">
        <label class="field-label">
          显示名称
          <input
            v-model="appBuildUploadName"
            :disabled="uploadingAppBuild"
            autocomplete="off"
            placeholder="默认使用文件名"
          />
        </label>
        <label class="field-label">
          安装包文件
          <input
            type="file"
            accept=".apk,.apex,.xapk,.ipa,application/vnd.android.package-archive"
            required
            :disabled="uploadingAppBuild"
            @change="exec.onAppBuildFileChange"
          />
        </label>
        <p v-if="appBuildMsg && !appBuildMsgOk" class="msg bad" role="alert">{{ appBuildMsg }}</p>
        <footer class="ap-modal-actions">
          <button type="button" class="ghost" :disabled="uploadingAppBuild" @click="closeUpload">取消</button>
          <button type="submit" class="primary" :disabled="uploadingAppBuild || !appBuildUploadFile">
            {{ uploadingAppBuild ? "正在上传…" : "开始上传" }}
          </button>
        </footer>
      </form>
    </ApModal>
  </section>
</template>

<style scoped>
.list-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
}

.list-toolbar input {
  flex: 0 1 16rem;
  min-width: 0;
}

.entry-name {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.entry-meta {
  display: block;
  margin-top: var(--space-1);
  color: var(--muted);
  font-size: var(--font-size-caption, 0.75rem);
  overflow-wrap: anywhere;
}

.nowrap {
  white-space: nowrap;
}

.version-code {
  color: var(--muted);
}

.danger-item {
  color: var(--danger-soft-fg);
}

.upload-form,
.field-label {
  display: grid;
  gap: var(--space-2);
}

.upload-form {
  gap: var(--space-4);
}

.field-label {
  font-size: 0.85rem;
}
</style>
