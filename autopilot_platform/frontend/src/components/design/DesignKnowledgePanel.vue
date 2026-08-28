<script setup lang="ts">
defineOptions({ name: "DesignKnowledgePanel" });

import { computed, onActivated, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
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
import DesignWorkflowBar from "./DesignWorkflowBar.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import { useCapabilities } from "../../composables/useCapabilities";

const shell = useShellStore();
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

async function reload() {
  loading.value = true;
  error.value = "";
  try {
    const confirmedFilter =
      confirmed.value === "true" ? true : confirmed.value === "false" ? false : undefined;
    const out = await listKnowledgePage({
      projectId: filterProjectId.value,
      q: listQDebounced.value,
      category: category.value || undefined,
      confirmed: confirmedFilter,
      sortBy: sortBy.value,
      order: order.value,
      page: page.value,
      pageSize: pageSize.value,
    });
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
    error.value = e?.message || String(e);
  } finally {
    loading.value = false;
    hasLoaded.value = true;
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
  () => filterProjectId.value,
  () => {
    page.value = 1;
    universeEmpty.value = false;
    void reload();
  },
);

async function onSearch() {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶部选择项目";
    return;
  }
  if (!searchQuery.value.trim()) {
    error.value = "请输入检索关键词";
    return;
  }
  searchBusy.value = true;
  error.value = "";
  try {
    const out = await searchKnowledge({
      project_id: projectId,
      query: searchQuery.value.trim(),
      score_threshold: searchThreshold.value,
    });
    searchResults.value = out.documents || [];
    searchEngine.value = out.engine || "";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    searchBusy.value = false;
  }
}

async function onRebuildIndex() {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶部选择项目";
    return;
  }
  if (
    !(await confirmDialog("重建向量索引会清空并重新写入当前项目知识，是否继续？", {
      danger: true,
    }))
  ) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await rebuildKnowledgeIndex({ project_id: projectId, clear_all: true });
    notice.value = out.message || `索引重建完成（${out.indexed_count ?? 0} 条）`;
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onBatchDelete() {
  if (!selectedIds.value.length) {
    error.value = "请先勾选要删除的知识条目";
    return;
  }
  if (
    !(await confirmDialog(
      `批量删除 ${selectedIds.value.length} 条知识？此操作不可撤销。`,
      { danger: true },
    ))
  ) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await batchDeleteKnowledge(selectedIds.value);
    notice.value = out.message || `已删除 ${out.deleted_count ?? selectedIds.value.length} 条`;
    listCard.value?.clearSelection();
    selectedIds.value = [];
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
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
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶部选择项目";
    return;
  }
  if (!payload.title.trim() || !payload.content.trim()) {
    error.value = "标题与内容不能为空";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await createKnowledge({
      project_id: projectId,
      title: payload.title,
      content: payload.content,
      category: payload.category,
      confirmed: payload.confirmed,
    });
    form.value?.clear();
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
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
  if (!payload.title.trim()) {
    error.value = "标题不能为空";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await updateKnowledge(editing.value.id, payload);
    editing.value = null;
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
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
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶部选择项目";
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
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onRemove(item: KnowledgeItem) {
  if (
    !(await confirmDialog(`删除知识条目「${item.title}」？`, {
      danger: true,
    }))
  ) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteKnowledge(item.id);
    if (editing.value?.id === item.id) editing.value = null;
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

let _skipActivateReload = false;
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
  <div class="page-stack knowledge-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>知识库</h2>
        <p class="lede">记下常用规则，生成用例时可以引用。不是必填项。</p>
      </div>
      <div class="page-hero-actions">
        <button
          v-if="canEdit"
          type="button"
          class="small"
          :disabled="busy || !!ctx?.missing"
          @click="onRebuildIndex"
        >
          重建索引
        </button>
        <button
          v-if="canEdit"
          type="button"
          class="small danger"
          :disabled="busy || !selectedIds.length"
          @click="onBatchDelete"
        >
          批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : "" }}
        </button>
        <button type="button" class="ghost small" :disabled="loading || busy" @click="reload">
          刷新
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad">{{ error }}</div>
    <div v-if="notice" class="msg ok">{{ notice }}</div>

    <ProjectContextBanner ref="ctx" />
    <ProjectReadonlyBanner />
    <DesignWorkflowBar page="knowledge" />

    <div class="skip-bar">
      <span class="meta-line">知识库非必填。日常生成请先去意图用例粘贴需求。</span>
      <button type="button" class="primary small" @click="shell.activeTab = 'design-cases'">
        跳过，去生成用例
      </button>
    </div>

    <details class="fold-card surface-card">
      <summary class="fold-summary">
        <span>语义检索</span>
        <span class="fold-hint">向量相似度命中（与下方列表筛选独立）</span>
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
          <p class="empty-desc">暂无命中结果，可调低阈值或补充知识条目。</p>
        </div>
      </div>
    </details>

    <details v-if="canEdit" class="fold-card surface-card">
      <summary class="fold-summary">
        <span>批量导入</span>
        <span class="fold-hint">多文件入库，默认折叠避免占满首屏</span>
      </summary>
      <KnowledgeImportCard
        ref="importCard"
        bare
        :busy="busy"
        :disabled="!!ctx?.missing"
        @import="onImport"
      />
    </details>

    <KnowledgeCreateForm v-if="canEdit && !editing" ref="form" :busy="busy" @create="onCreate" />
    <KnowledgeEditForm
      v-if="canEdit"
      :item="editing"
      :busy="busy"
      @save="onSaveEdit"
      @cancel="editing = null"
    />
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
    />
  </div>
</template>

<style scoped>
.knowledge-panel {
  width: 100%;
  min-width: 0;
}
.msg.bad {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
  font-size: 0.85rem;
}
.msg.ok {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
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
  border-radius: 8px;
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
.skip-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  padding: 0.65rem 0.85rem;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: var(--surface-soft);
}
</style>
