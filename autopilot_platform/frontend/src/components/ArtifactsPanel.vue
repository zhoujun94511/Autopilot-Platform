<script setup lang="ts">
defineOptions({ name: "ArtifactsPanel" });

import { storeToRefs } from "pinia";
import { computed, ref, watch } from "vue";
import type { Artifact } from "../api";
import { listArtifactsPage, OPS_LIST_PAGE_SIZE } from "../api/opsLists";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";
import { usePagedList } from "../composables/usePagedList";
import { useExecStore } from "../stores/execution";
import { useOpsStore } from "../stores/opsStore";
import DataPager from "./common/DataPager.vue";
import ExecProjectGateBanner from "./ExecProjectGateBanner.vue";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const exec = useExecStore();
const ops = useOpsStore();
const { artifactsVersion, artMsg, artMsgOk, uploadName } = storeToRefs(exec);
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
  resetSources: [() => filterProjectId.value],
});

const { items, total, page, pageSize, loading, hasLoaded, reload, setPage, setPageSize } = list;

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

function openUpload() {
  artMsg.value = "";
  uploadOpen.value = true;
}

function closeUpload() {
  uploadOpen.value = false;
}

watch(artMsg, (m) => {
  if (uploadOpen.value && artMsgOk.value && String(m || "").startsWith("已上传")) {
    uploadOpen.value = false;
  }
});
</script>

<template>
  <section class="panel page-stack artifacts-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>工程制品</h2>
        <p class="lede">存放从 IDE 上传的工程压缩包，可上传或清理过期文件。</p>
      </div>
      <div class="page-hero-actions">
        <button
          v-if="canUpload"
          type="button"
          class="primary small"
          @click="openUpload"
        >
          上传制品
        </button>
        <details v-if="caps.canOps" class="action-menu">
          <summary class="small">更多</summary>
          <div class="action-menu-panel">
            <button
              type="button"
              class="danger-item"
              title="按保留天数清理过期压缩包"
              @click="exec.onPurgeArtifacts"
            >
              清理超期
            </button>
          </div>
        </details>
      </div>
    </header>

    <ExecProjectGateBanner action-hint="上传制品" />

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>编号</th>
            <th>名称</th>
            <th>文件名</th>
            <th>大小</th>
            <th>校验</th>
            <th>上传人</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!items.length && hasLoaded">
            <td class="empty" colspan="7">
              <div class="empty-stack">
                <span>还没有工程压缩包</span>
                <button type="button" class="linkish-cta" @click="openUpload">去上传</button>
              </div>
            </td>
          </tr>
          <tr v-for="a in items" :key="a.id">
            <td class="mono">
              <button
                type="button"
                class="small art-id-btn"
                title="选中后，创建任务时可直接用这个压缩包"
                @click="exec.selectArtifact(a.id)"
              >
                {{ a.id.slice(0, 8) }}…
              </button>
            </td>
            <td class="art-name-cell">{{ a.name || "-" }}</td>
            <td class="mono font-semibold">{{ a.filename }}</td>
            <td>{{ formatBytes(a.size_bytes) }}</td>
            <td>
              <span
                class="manifest-pill"
                :class="a.manifest_status || 'unknown'"
                :title="
                  [...(a.manifest_errors || []), ...(a.manifest_warnings || [])].join('\n') ||
                  '无校验信息'
                "
              >
                {{ a.manifest_status || "n/a"
                }}{{ a.manifest_version ? ` @${a.manifest_version}` : "" }}
              </span>
            </td>
            <td>
              <span class="user-pill">{{ a.uploaded_by }}</span>
            </td>
            <td>
              <div class="action-btn-group">
                <button
                  type="button"
                  class="small"
                  title="选中后可把这个压缩包分享给别人"
                  @click="ops.selectArtifactForShare(a.id)"
                >
                  <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" stroke-width="2" fill="none">
                    <circle cx="18" cy="5" r="3" />
                    <circle cx="6" cy="12" r="3" />
                    <circle cx="18" cy="19" r="3" />
                    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                  </svg>
                  分享
                </button>
                <button
                  type="button"
                  class="small danger"
                  title="删除这个压缩包"
                  @click="exec.onDeleteArtifact(a.id)"
                >
                  <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" stroke-width="2" fill="none">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
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
      <div v-if="uploadOpen" class="modal-mask" @click.self="closeUpload">
        <section
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="artifact-upload-title"
        >
          <header class="modal-head">
            <div>
              <h3 id="artifact-upload-title">上传工程制品</h3>
              <p class="modal-sub">上传 zip 用例归档包，可选填写显示名称。</p>
            </div>
            <button type="button" class="icon-btn" aria-label="关闭" @click="closeUpload">✕</button>
          </header>
          <form class="modal-body" @submit.prevent="exec.onUpload">
            <label class="field-label">
              名称
              <input v-model="uploadName" placeholder="例如: Release_v1.0.4_B3" />
            </label>
            <label class="field-label">
              Zip 用例归档包 *
              <input
                type="file"
                accept=".zip,application/zip"
                required
                class="real-file-input"
                @change="exec.onFileChange"
              />
            </label>
            <p v-if="artMsg" class="msg" :class="artMsgOk ? 'ok' : 'bad'">
              {{ artMsg }}
            </p>
            <footer class="modal-actions">
              <button type="button" class="ghost" @click="closeUpload">取消</button>
              <button type="submit" class="primary">开始上传</button>
            </footer>
          </form>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.artifacts-panel {
  width: 100%;
  max-width: none;
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

.font-semibold {
  font-weight: 600;
}

.user-pill {
  font-size: 0.75rem;
  background-color: var(--control-bg);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  border: 1px solid var(--line);
  color: var(--muted);
}

.manifest-pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  border: 1px solid var(--line);
  text-transform: lowercase;
}
.manifest-pill.valid {
  color: var(--ok-soft-fg);
  background: var(--ok-soft-bg);
  border-color: var(--ok-soft-border);
}
.manifest-pill.missing {
  color: var(--warning-soft-fg);
  background: var(--warning-soft-bg);
  border-color: var(--warning-soft-border);
}
.manifest-pill.invalid {
  color: var(--danger-soft-fg);
  background: var(--danger-soft-bg);
  border-color: var(--danger-soft-border);
}
.manifest-pill.unknown,
.manifest-pill.n\/a {
  color: var(--muted);
}

.action-btn-group {
  display: flex;
  gap: 0.4rem;
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

.danger-item {
  color: var(--bad) !important;
}

.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  background: var(--overlay);
}

.modal-card {
  width: min(480px, 100%);
  background: var(--surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevated-shadow);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.1rem 1.2rem 0.85rem;
  border-bottom: 1px solid var(--line);
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
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1.1rem 1.2rem 1.2rem;
}

.field-label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.real-file-input {
  cursor: pointer;
  padding: 0.4rem 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.25rem;
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
</style>
