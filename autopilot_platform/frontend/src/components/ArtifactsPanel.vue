<script setup lang="ts">
defineOptions({ name: "ArtifactsPanel" });

import { storeToRefs } from "pinia";
import { computed, onDeactivated, ref, watch } from "vue";
import type { Artifact } from "../api";
import { listArtifactsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { workspaceScopeVersion } from "../composables/mcProjectsState";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";
import ApModal from "./ApModal.vue";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const { artifactsVersion, artMsg, artMsgOk, uploadName, uploadFile, uploadingArtifact, form } = storeToRefs(exec);
const caps = useCapabilities();
const uploadOpen = ref(false);
const canUpload = computed(() => Boolean(caps.canEditProject));

const list = usePagedList<Artifact>({
  immediate: false,
  pageSize: OPS_LIST_PAGE_SIZE,
  fetchPage: ({ page, pageSize }) =>
    listArtifactsPage({
      page,
      pageSize,
      projectId: filterProjectId.value.trim() || undefined,
    }),
  resetSources: [workspaceScopeVersion],
});

const { items, total, page, pageSize, loading, hasLoaded, error, reload, setPage, setPageSize } = list;

watch(artifactsVersion, () => void reload(false));
void reload(true);

function formatBytes(bytes: number, decimals = 2) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
}

const manifestLabels: Record<string, string> = { valid: "通过", missing: "缺少清单", invalid: "校验失败" };

function openUpload() {
  if (uploadingArtifact.value || !canUpload.value) return;
  artMsg.value = "";
  uploadOpen.value = true;
}

function closeUpload() {
  if (uploadingArtifact.value) return;
  uploadOpen.value = false;
  uploadFile.value = null;
}

async function submitUpload(event: Event) {
  if (await exec.onUpload(event)) closeUpload();
}

function resetUpload() {
  uploadOpen.value = false;
  uploadFile.value = null;
}

onDeactivated(resetUpload);
watch(workspaceScopeVersion, resetUpload);
</script>

<template>
  <section class="panel page-stack data-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>工程制品</h2>
      </div>
      <div class="page-hero-actions">
        <button
          v-if="canUpload"
          type="button"
          class="primary small"
          :disabled="uploadingArtifact"
          @click="openUpload"
        >上传制品</button>
        <details v-if="caps.canOps" class="action-menu">
          <summary class="small">更多</summary>
          <div class="action-menu-panel">
            <button type="button" class="danger-item" @click="exec.onPurgeArtifacts">
              清理过期制品
            </button>
          </div>
        </details>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="上传制品" />
    <p v-if="artMsg && artMsgOk && !uploadOpen" class="msg ok" role="status">{{ artMsg }}</p>

    <div class="table-wrap">
      <table aria-label="工程制品" :aria-busy="loading">
        <thead>
          <tr>
            <th scope="col">制品</th>
            <th scope="col">校验</th>
            <th scope="col">大小</th>
            <th scope="col">上传者</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && !hasLoaded">
            <td class="empty" colspan="5">正在加载制品…</td>
          </tr>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="5">
              <div v-if="error" class="empty-stack">
                <span role="alert">{{ error }}</span>
                <button type="button" class="linkish" @click="reload()">重试</button>
              </div>
              <span v-else>暂无工程制品</span>
            </td>
          </tr>
          <tr v-for="artifact in items" :key="artifact.id">
            <td>
              <span class="entry-name">{{ artifact.name || artifact.filename }}</span>
              <span v-if="artifact.name && artifact.name !== artifact.filename" class="entry-meta mono">
                {{ artifact.filename }}
              </span>
              <span class="entry-meta mono" :title="artifact.id">{{ artifact.id.slice(0, 8) }}…</span>
            </td>
            <td>
              <span
                class="manifest-state"
                :class="artifact.manifest_status"
                :title="[...(artifact.manifest_errors || []), ...(artifact.manifest_warnings || [])].join('\n')"
              >
                {{ manifestLabels[artifact.manifest_status || ""] || artifact.manifest_status || "未校验" }}
              </span>
              <span v-if="artifact.manifest_version" class="entry-meta">{{ artifact.manifest_version }}</span>
            </td>
            <td class="mono size-cell">{{ formatBytes(artifact.size_bytes) }}</td>
            <td>{{ artifact.uploaded_by || "—" }}</td>
            <td>
              <div class="row-actions">
                <button
                  type="button"
                  class="linkish small"
                  :title="artifact.id"
                  :aria-pressed="form.artifact_id === artifact.id"
                  @click="exec.selectArtifact(artifact.id)"
                >{{ form.artifact_id === artifact.id ? "已选用" : "选用" }}</button>
                <button type="button" class="linkish small" @click="ops.selectArtifactForShare(artifact.id)">分享</button>
                <button type="button" class="linkish small danger-item" @click="exec.onDeleteArtifact(artifact.id)">删除</button>
              </div>
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
      v-if="uploadOpen"
      title="上传工程制品"
      wide
      :close-on-backdrop="!uploadingArtifact"
      :close-on-esc="!uploadingArtifact"
      @close="closeUpload"
    >
      <form class="upload-form" :aria-busy="uploadingArtifact" @submit.prevent="submitUpload">
        <label class="field-label">
          显示名称
          <input v-model="uploadName" :disabled="uploadingArtifact" autocomplete="off" placeholder="默认使用文件名" />
        </label>
        <label class="field-label">
          ZIP 文件
          <input
            type="file"
            accept=".zip,application/zip"
            required
            :disabled="uploadingArtifact"
            @change="exec.onFileChange"
          />
        </label>
        <p v-if="artMsg && !artMsgOk" class="msg bad" role="alert">{{ artMsg }}</p>
        <footer class="ap-modal-actions">
          <button type="button" class="ghost" :disabled="uploadingArtifact" @click="closeUpload">取消</button>
          <button type="submit" class="primary" :disabled="uploadingArtifact || !uploadFile">
            {{ uploadingArtifact ? "正在上传…" : "开始上传" }}
          </button>
        </footer>
      </form>
    </ApModal>
  </section>
</template>

<style scoped>
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

.size-cell {
  white-space: nowrap;
}

.manifest-state.valid { color: var(--ok-soft-fg); }
.manifest-state.missing { color: var(--warning-soft-fg); }
.manifest-state.invalid,
.danger-item { color: var(--danger-soft-fg); }

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
