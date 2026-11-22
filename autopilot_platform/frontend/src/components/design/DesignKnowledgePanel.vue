<script setup lang="ts">
defineOptions({ name: "DesignKnowledgePanel" });

import { computed, onActivated, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { workspaceScopeVersion } from "../../composables/mcProjectsState";
import { useManualPageRefresh } from "../../composables/useManualPageRefresh";
import { useDebouncedValue } from "../../composables/useDesignListQuery";
import { confirmDialog } from "../../composables/useNotify";
import { DEFAULT_PAGE_SIZE } from "../../api/designList";
import {
  batchDeleteKnowledge,
  createKnowledge,
  deleteKnowledge,
  importKnowledgeFiles,
  listKnowledgePage,
  rebuildKnowledgeIndex,
  searchKnowledge,
  updateKnowledge,
  type KnowledgeItem,
  type KnowledgeSearchHit,
} from "../../api/designKnowledge";
import KnowledgeCreateForm from "./KnowledgeCreateForm.vue";
import KnowledgeEditForm from "./KnowledgeEditForm.vue";
import KnowledgeImportCard from "./KnowledgeImportCard.vue";
import KnowledgeListCard from "./KnowledgeListCard.vue";
import ApModal from "../ApModal.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import { useCapabilities } from "../../composables/useCapabilities";

const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);

const caps = useCapabilities();
const canEdit = computed(() => Boolean(caps.canEditProject));
const items = ref<KnowledgeItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const category = ref("");
const confirmed = ref("");
const sortBy = ref("created_at");
const order = ref<"asc" | "desc">("desc");
const { value: listQ, debounced: listQDebounced } = useDebouncedValue("", 300);

const loading = ref(false);
const hasLoaded = ref(false);
const universeEmpty = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const form = ref<{ clear: () => void } | null>(null);
const createOpen = ref(false);
const createError = ref("");
const importCard = ref<{ clearFiles: () => void } | null>(null);
const listCard = ref<{ clearSelection: () => void } | null>(null);
const editing = ref<KnowledgeItem | null>(null);
const ctx = ref<{ missing: boolean } | null>(null);

const searchQuery = ref("");
const searchThreshold = ref(0.3);
const searchBusy = ref(false);
const searchResults = ref<KnowledgeSearchHit[]>([]);
const searchEngine = ref("");
const selectedIds = ref<string[]>([]);
let listRequestId = 0;
let searchRequestId = 0;

async function reload() {
  const projectId = filterProjectId.value.trim();
  if (!projectId) return;
  const scope = workspaceScopeVersion.value;
  const requestId = ++listRequestId;
  const current = () => scope === workspaceScopeVersion.value && requestId === listRequestId;
  loading.value = true;
  error.value = "";
  try {
    const confirmedFilter =
      confirmed.value === "true" ? true : confirmed.value === "false" ? false : undefined;
    const out = await listKnowledgePage({
      projectId,
      q: listQDebounced.value,
      category: category.value || undefined,
      confirmed: confirmedFilter,
      sortBy: sortBy.value,
      order: order.value,
      page: page.value,
      pageSize: pageSize.value,
    });
    if (!current()) return;
    items.value = out.items;
    total.value = out.total;
    pageSize.value = out.page_size;
    if (out.items.length === 0 && out.total > 0 && out.page > 1) {
      universeEmpty.value = false;
      page.value = Math.max(1, Math.ceil(out.total / out.page_size));
      return;
    }
    if (out.total > 0) universeEmpty.value = false;
    else if (
      !listQDebounced.value.trim() &&
      !category.value &&
      !confirmed.value
    ) {
      universeEmpty.value = true;
    }
    page.value = out.page;
  } catch (e: any) {
    if (current()) error.value = e?.message || String(e);
  } finally {
    if (current()) {
      loading.value = false;
      hasLoaded.value = true;
    }
  }
}

function resetPageAndReload() {
  if (page.value !== 1) page.value = 1;
  else void reload();
}

watch(listQDebounced, () => {
  if (universeEmpty.value) return;
  resetPageAndReload();
});
watch([category, confirmed, sortBy, order], () => {
  if (universeEmpty.value) return;
  resetPageAndReload();
});
watch(page, () => {
  void reload();
});
watch(pageSize, () => {
  if (page.value !== 1) page.value = 1;
  else void reload();
});
watch(
  workspaceScopeVersion,
  () => {
    const pageChanged = page.value !== 1;
    page.value = 1;
    items.value = [];
    total.value = 0;
    loading.value = false;
    hasLoaded.value = false;
    universeEmpty.value = false;
    error.value = "";
    notice.value = "";
    createOpen.value = false;
    createError.value = "";
    editing.value = null;
    selectedIds.value = [];
    listCard.value?.clearSelection();
    importCard.value?.clearFiles();
    searchBusy.value = false;
    searchResults.value = [];
    searchEngine.value = "";
    if (!pageChanged) void reload();
  },
);

async function onSearch() {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  if (!searchQuery.value.trim()) {
    error.value = "请输入检索关键词";
    return;
  }
  const scope = workspaceScopeVersion.value;
  const requestId = ++searchRequestId;
  const current = () => scope === workspaceScopeVersion.value && requestId === searchRequestId;
  searchBusy.value = true;
  error.value = "";
  try {
    const out = await searchKnowledge({
      project_id: projectId,
      query: searchQuery.value.trim(),
      score_threshold: searchThreshold.value,
    });
    if (!current()) return;
    searchResults.value = out.documents || [];
    searchEngine.value = out.engine || "";
  } catch (e: any) {
    if (current()) error.value = e?.message || String(e);
  } finally {
    if (current()) searchBusy.value = false;
  }
}

async function onRebuildIndex() {
  const scope = workspaceScopeVersion.value;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  if (
    !(await confirmDialog("重建向量索引会清空并重新写入当前项目知识，是否继续？", {
      danger: true,
    }))
  ) return;
  if (scope !== workspaceScopeVersion.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await rebuildKnowledgeIndex({ project_id: projectId, clear_all: true });
    if (scope !== workspaceScopeVersion.value) return;
    notice.value = out.message || `索引重建完成（${out.indexed_count ?? 0} 条）`;
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onBatchDelete() {
  const scope = workspaceScopeVersion.value;
  const ids = [...selectedIds.value];
  if (!ids.length) {
    error.value = "请先勾选要删除的知识条目";
    return;
  }
  if (
    !(await confirmDialog(
      `批量删除 ${ids.length} 条知识？此操作不可撤销。`,
      { danger: true },
    ))
  ) return;
  if (scope !== workspaceScopeVersion.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await batchDeleteKnowledge(ids);
    if (scope !== workspaceScopeVersion.value) return;
    notice.value = out.message || `已删除 ${out.deleted_count ?? ids.length} 条`;
    listCard.value?.clearSelection();
    selectedIds.value = [];
    await reload();
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onCreate(payload: {
  title: string;
  content: string;
  category: string;
  confirmed: boolean;
}) {
  if (busy.value) return;
  const scope = workspaceScopeVersion.value;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    createError.value = "请先选择项目";
    return;
  }
  if (!payload.title.trim() || !payload.content.trim()) {
    createError.value = "标题与内容不能为空";
    return;
  }
  busy.value = true;
  createError.value = "";
  try {
    await createKnowledge({
      project_id: projectId,
      title: payload.title,
      content: payload.content,
      category: payload.category,
      confirmed: payload.confirmed,
    });
    if (scope !== workspaceScopeVersion.value) return;
    form.value?.clear();
    createOpen.value = false;
    await reload();
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) createError.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onSaveEdit(payload: {
  title: string;
  content: string;
  category: string;
  confirmed: boolean;
}) {
  if (!editing.value) return;
  const scope = workspaceScopeVersion.value;
  if (!payload.title.trim()) {
    error.value = "标题不能为空";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await updateKnowledge(editing.value.id, payload);
    if (scope !== workspaceScopeVersion.value) return;
    editing.value = null;
    await reload();
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onImport(payload: {
  files: File[];
  category: string;
  confirmed: boolean;
  description: string;
}) {
  const scope = workspaceScopeVersion.value;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  if (!payload.files.length) {
    error.value = "请先选择要导入的文件";
    return;
  }
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await importKnowledgeFiles({
      projectId,
      files: payload.files,
      category: payload.category,
      confirmed: payload.confirmed,
      description: payload.description,
    });
    if (scope !== workspaceScopeVersion.value) return;
    const summary = out.summary || {};
    const failed = Number(summary.failed_count || 0);
    const okFiles = Number(summary.success_count || 0);
    const itemsN = Number(summary.item_count || 0);
    notice.value =
      out.message ||
      `导入完成：成功 ${okFiles} 个文件，共 ${itemsN} 条知识` +
        (failed ? `，失败 ${failed} 个文件` : "");
    if (failed) {
      const details = (out.results || [])
        .filter((r) => !r.success)
        .map((r) => `${r.filename}: ${r.message || "失败"}`)
        .slice(0, 5);
      if (details.length) {
        error.value = details.join("；");
      }
    }
    if (okFiles > 0) {
      importCard.value?.clearFiles();
      await reload();
    }
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onRemove(item: KnowledgeItem) {
  const scope = workspaceScopeVersion.value;
  if (
    !(await confirmDialog(`删除知识条目「${item.title}」？`, {
      danger: true,
    }))
  ) return;
  if (scope !== workspaceScopeVersion.value) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteKnowledge(item.id);
    if (scope !== workspaceScopeVersion.value) return;
    if (editing.value?.id === item.id) editing.value = null;
    await reload();
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

let _skipActivateReload = false;
useManualPageRefresh("design-knowledge", reload);
onMounted(() => {
  _skipActivateReload = true;
  void reload();
});
onActivated(() => {
  if (_skipActivateReload) {
    _skipActivateReload = false;
    return;
  }
  void reload();
});
</script>

<template>
  <div class="page-stack data-page knowledge-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>知识库</h2>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="ghost small" :disabled="loading || busy" @click="reload">
          刷新
        </button>
        <button
          v-if="canEdit"
          type="button"
          class="primary small"
          :disabled="busy"
          @click="createError = ''; createOpen = true"
        >
          新增知识
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad" role="alert">{{ error }}</div>
    <div v-if="notice" class="msg ok" role="status">{{ notice }}</div>

    <ProjectContextBanner ref="ctx" />
    <ProjectReadonlyBanner />
    <KnowledgeListCard
      ref="listCard"
      v-model:q="listQ"
      v-model:category="category"
      v-model:confirmed="confirmed"
      v-model:sort-by="sortBy"
      v-model:order="order"
      v-model:page="page"
      v-model:page-size="pageSize"
      :items="items"
      :total="total"
      :loading="loading"
      :has-loaded="hasLoaded"
      :busy="busy"
      :readonly="!canEdit"
      @edit="editing = $event"
      @remove="onRemove"
      @selection-change="selectedIds = $event"
    >
      <template v-if="canEdit && selectedIds.length" #bulk-actions>
        <button type="button" class="small danger" :disabled="busy" @click="onBatchDelete">
          删除所选（{{ selectedIds.length }}）
        </button>
      </template>
    </KnowledgeListCard>

    <details class="fold-card knowledge-tool">
      <summary class="fold-summary">
        <span>语义检索</span>
      </summary>
      <div class="field-stack">
        <div class="inline-fields">
          <label class="field-label flex-grow">
            检索词
            <input
              v-model="searchQuery"
              type="text"
              placeholder="输入问题或关键词，匹配相关知识…"
              @keydown.enter.prevent="onSearch"
            />
          </label>
          <label class="field-label compact">
            相似度阈值
            <input v-model.number="searchThreshold" type="number" min="0" max="1" step="0.05" />
          </label>
          <button type="button" class="primary search-btn" :disabled="searchBusy" @click="onSearch">
            检索
          </button>
        </div>
        <p v-if="searchEngine" class="meta-line">引擎：{{ searchEngine }}</p>
        <div v-if="searchResults.length" class="search-results">
          <div v-for="hit in searchResults" :key="hit.id" class="search-hit">
            <div class="hit-head">
              <span class="hit-title">{{ hit.title }}</span>
              <span class="pill">{{ hit.score.toFixed(3) }}</span>
            </div>
            <p class="hit-body">{{ hit.content.slice(0, 240) }}{{ hit.content.length > 240 ? "…" : "" }}</p>
          </div>
        </div>
        <div v-else-if="searchQuery && !searchBusy" class="empty-state compact">
          <p class="empty-desc">无匹配结果</p>
        </div>
        <button
          v-if="canEdit"
          type="button"
          class="ghost small index-action"
          :disabled="busy || !!ctx?.missing"
          @click="onRebuildIndex"
        >
          重建索引
        </button>
      </div>
    </details>

    <details v-if="canEdit" class="fold-card knowledge-tool">
      <summary class="fold-summary">
        <span>批量导入</span>
      </summary>
      <KnowledgeImportCard
        ref="importCard"
        bare
        :busy="busy"
        :disabled="!!ctx?.missing"
        @import="onImport"
      />
    </details>

    <ApModal
      v-if="canEdit && createOpen"
      title="新增知识"
      variant="drawer"
      :close-on-backdrop="false"
      :close-on-esc="!busy"
      @close="createOpen = false"
    >
      <p v-if="createError" class="msg bad" role="alert">{{ createError }}</p>
      <KnowledgeCreateForm ref="form" bare :busy="busy" @create="onCreate" />
      <template #actions>
        <button type="button" :disabled="busy" @click="createOpen = false">关闭</button>
      </template>
    </ApModal>
    <KnowledgeEditForm
      v-if="canEdit"
      :item="editing"
      :busy="busy"
      @save="onSaveEdit"
      @cancel="editing = null"
    />
  </div>
</template>

<style scoped>
.knowledge-panel {
  width: 100%;
  min-width: 0;
}
.knowledge-tool {
  border-top: 1px solid var(--line-soft);
}
.index-action {
  align-self: flex-start;
}
.msg.bad {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
  font-size: 0.85rem;
}
.msg.ok {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  background: var(--ok-soft-bg);
  border: 1px solid var(--ok-soft-border);
  color: var(--ok-soft-fg);
  font-size: 0.85rem;
}
.inline-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  align-items: flex-end;
}
.field-label.flex-grow {
  flex: 1;
  min-width: 12rem;
}
.field-label.compact {
  min-width: 6rem;
}
.search-btn {
  align-self: flex-end;
  margin-bottom: 0.1rem;
}
.search-results {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin-top: 0.35rem;
}
.search-hit {
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--chip-bg);
}
.hit-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}
.hit-title {
  font-weight: 600;
  font-size: 0.88rem;
}
.hit-body {
  margin: 0;
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.45;
}
.empty-state.compact {
  padding: 0.5rem 0;
}
</style>
