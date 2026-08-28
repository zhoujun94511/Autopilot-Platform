<script setup lang="ts">
defineOptions({ name: "DesignDocsPanel" });

import { computed, onActivated, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { useDebouncedValue } from "../../composables/useDesignListQuery";
import { confirmDialog } from "../../composables/useNotify";
import { DEFAULT_PAGE_SIZE } from "../../api/designList";
import {
  analyzeDocument,
  batchDeleteDocuments,
  deleteDocument,
  exportRequirementsExcel,
  formatAnalysisNotice,
  importDocuments,
  importRequirementFiles,
  listAnalysisHistoryPage,
  listDocuments,
  listDocumentsPage,
  previewDocument,
  reanalyzeDocument,
  type AnalysisHistoryItem,
  type DesignDocument,
  type DocumentPreview,
  type Requirement,
} from "../../api/designDocs";
import {
  batchDeleteRequirements,
  deleteRequirement,
  listRequirementsPage,
  updateRequirement,
} from "../../api/designRequirements";
import { generateLogicalCases } from "../../api/designCases";
import DocsImportCard from "./DocsImportCard.vue";
import RequirementsImportCard from "./RequirementsImportCard.vue";
import DocsListCard from "./DocsListCard.vue";
import ReqsListCard from "./ReqsListCard.vue";
import ReqEditForm from "./ReqEditForm.vue";
import DesignWorkflowBar from "./DesignWorkflowBar.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import ListPager from "./ListPager.vue";
import ApSelect from "../common/ApSelect.vue";
import { useCapabilities } from "../../composables/useCapabilities";

const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);

const caps = useCapabilities();
const canEdit = computed(() => Boolean(caps.canEditProject));
const docs = ref<DesignDocument[]>([]);
const docsTotal = ref(0);
const docsPage = ref(1);
const docsPageSize = ref(DEFAULT_PAGE_SIZE);
const docsFileType = ref("");
const docsSortBy = ref("created_at");
const docsOrder = ref<"asc" | "desc">("desc");
const { value: docsQ, debounced: docsQDebounced } = useDebouncedValue("", 300);

const reqs = ref<Requirement[]>([]);
const reqsTotal = ref(0);
const reqsPage = ref(1);
const reqsPageSize = ref(DEFAULT_PAGE_SIZE);
const reqsPriority = ref("");
const reqsSortBy = ref("created_at");
const reqsOrder = ref<"asc" | "desc">("desc");
const sourceDocFilter = ref("");
const { value: reqsQ, debounced: reqsQDebounced } = useDebouncedValue("", 300);

const docOptions = ref<DesignDocument[]>([]);
const history = ref<AnalysisHistoryItem[]>([]);
const historyTotal = ref(0);
const historyPage = ref(1);
const historyPageSize = ref(DEFAULT_PAGE_SIZE);
const loading = ref(false);
const hasLoaded = ref(false);
const error = ref("");
const info = ref("");
const infoGotoCases = ref(false);
const busy = ref(false);
const editingReq = ref<Requirement | null>(null);
const docsImport = ref<{ clearFiles: () => void } | null>(null);
const reqsImport = ref<{ clearFiles: () => void } | null>(null);
const docsList = ref<{ clearSelection: () => void } | null>(null);
const reqsList = ref<{ clearSelection: () => void } | null>(null);
const previewOpen = ref(false);
const previewLoading = ref(false);
const previewData = ref<DocumentPreview | null>(null);
const analysisType = ref("requirements");

const analysisTypes = [
  { value: "requirements", label: "需求条目" },
  { value: "test_points", label: "测试点" },
  { value: "business_rules", label: "业务规则" },
  { value: "comprehensive", label: "综合分析" },
];

/** 三阶段工作区，避免一页纵向堆满 */
type DocsWorkspaceTab = "import" | "docs" | "reqs";
type ImportMode = "document" | "structured";
const workspaceTab = ref<DocsWorkspaceTab>("import");
const importMode = ref<ImportMode>("document");
const historyOpen = ref(false);
const tabTouched = ref(false);

function selectWorkspace(tab: DocsWorkspaceTab) {
  tabTouched.value = true;
  workspaceTab.value = tab;
}

function openDocsImport() {
  selectWorkspace("import");
  importMode.value = "document";
}

function preferWorkspaceTab() {
  if (tabTouched.value || loading.value) return;
  if (reqsTotal.value > 0) workspaceTab.value = "reqs";
  else if (docsTotal.value > 0) workspaceTab.value = "docs";
  else workspaceTab.value = "import";
}

watch([docsTotal, reqsTotal, loading], () => preferWorkspaceTab());

const docNameById = computed(() => {
  const m: Record<string, string> = {};
  for (const d of docOptions.value) m[d.id] = d.filename;
  for (const d of docs.value) m[d.id] = d.filename;
  return m;
});

async function reloadDocOptions() {
  const pid = filterProjectId.value?.trim();
  docOptions.value = await listDocuments(pid);
}

async function reloadDocs() {
  const pid = filterProjectId.value?.trim();
  const out = await listDocumentsPage({
    projectId: pid,
    q: docsQDebounced.value,
    fileType: docsFileType.value || undefined,
    sortBy: docsSortBy.value,
    order: docsOrder.value,
    page: docsPage.value,
    pageSize: docsPageSize.value,
  });
  docs.value = out.items;
  docsTotal.value = out.total;
  docsPageSize.value = out.page_size;
  if (out.items.length === 0 && out.total > 0 && out.page > 1) {
    docsPage.value = Math.max(1, Math.ceil(out.total / out.page_size));
    return;
  }
  docsPage.value = out.page;
}

async function reloadReqs() {
  const pid = filterProjectId.value?.trim();
  const out = await listRequirementsPage({
    projectId: pid,
    sourceDocumentId: sourceDocFilter.value.trim() || undefined,
    q: reqsQDebounced.value,
    priority: reqsPriority.value || undefined,
    sortBy: reqsSortBy.value,
    order: reqsOrder.value,
    page: reqsPage.value,
    pageSize: reqsPageSize.value,
  });
  reqs.value = out.items;
  reqsTotal.value = out.total;
  reqsPageSize.value = out.page_size;
  if (out.items.length === 0 && out.total > 0 && out.page > 1) {
    reqsPage.value = Math.max(1, Math.ceil(out.total / out.page_size));
    return;
  }
  reqsPage.value = out.page;
}

async function reloadHistory() {
  const out = await listAnalysisHistoryPage({
    projectId: filterProjectId.value?.trim(),
    documentId: sourceDocFilter.value.trim() || undefined,
    page: historyPage.value,
    pageSize: historyPageSize.value,
  });
  history.value = out.items;
  historyTotal.value = out.total;
  historyPageSize.value = out.page_size;
  if (out.items.length === 0 && out.total > 0 && out.page > 1) {
    historyPage.value = Math.max(1, Math.ceil(out.total / out.page_size));
    return;
  }
  historyPage.value = out.page;
}

async function reload() {
  loading.value = true;
  error.value = "";
  try {
    await Promise.all([reloadDocOptions(), reloadDocs(), reloadReqs(), reloadHistory()]);
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    loading.value = false;
    hasLoaded.value = true;
  }
}

function resetDocsPageAndReload() {
  if (docsPage.value !== 1) docsPage.value = 1;
  else void reloadDocs().catch((e) => (error.value = e?.message || String(e)));
}

function resetReqsPageAndReload() {
  if (reqsPage.value !== 1) reqsPage.value = 1;
  else void reloadReqs().catch((e) => (error.value = e?.message || String(e)));
}

watch(docsQDebounced, resetDocsPageAndReload);
watch([docsFileType, docsSortBy, docsOrder], resetDocsPageAndReload);
watch(docsPage, () => {
  void reloadDocs().catch((e) => (error.value = e?.message || String(e)));
});
watch(docsPageSize, () => {
  if (docsPage.value !== 1) docsPage.value = 1;
  else void reloadDocs().catch((e) => (error.value = e?.message || String(e)));
});

watch(reqsQDebounced, resetReqsPageAndReload);
watch([reqsPriority, reqsSortBy, reqsOrder, sourceDocFilter], () => {
  resetReqsPageAndReload();
  if (historyPage.value !== 1) historyPage.value = 1;
  else void reloadHistory().catch(() => undefined);
});
watch(reqsPage, () => {
  void reloadReqs().catch((e) => (error.value = e?.message || String(e)));
});
watch(reqsPageSize, () => {
  if (reqsPage.value !== 1) reqsPage.value = 1;
  else void reloadReqs().catch((e) => (error.value = e?.message || String(e)));
});
watch(historyPage, () => {
  void reloadHistory().catch(() => undefined);
});
watch(historyPageSize, () => {
  if (historyPage.value !== 1) historyPage.value = 1;
  else void reloadHistory().catch(() => undefined);
});

watch(
  () => filterProjectId.value,
  () => {
    docsPage.value = 1;
    reqsPage.value = 1;
    historyPage.value = 1;
    void reload();
  },
);

function requireProject(): string | null {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "需要先选择项目：设计域内容按项目隔离，请在顶部切换项目。";
    return null;
  }
  return projectId;
}

async function onDocsImport(payload: {
  files: File[];
  autoAnalyze: boolean;
  useLlm: boolean;
  analysisType: string;
  maxRequirements: number;
}) {
  const projectId = requireProject();
  if (!projectId) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await importDocuments({
      projectId,
      files: payload.files,
      autoAnalyze: payload.autoAnalyze,
      useLlm: payload.useLlm,
      analysisType: payload.analysisType,
      maxRequirements: payload.maxRequirements,
    });
    const base = out.message || "文档导入完成";
    info.value =
      out.degraded || out.summary?.degraded
        ? `${base}${base.includes("degraded") ? "" : " ⚠ AI 已降级为启发式——请人工审阅"}`
        : base;
    docsImport.value?.clearFiles();
    await reload();
    tabTouched.value = true;
    workspaceTab.value = reqsTotal.value > 0 ? "reqs" : "docs";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onReqsImport(payload: { files: File[] }) {
  const projectId = requireProject();
  if (!projectId) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await importRequirementFiles({ projectId, files: payload.files });
    info.value = out.message || "需求导入完成";
    reqsImport.value?.clearFiles();
    await reload();
    tabTouched.value = true;
    workspaceTab.value = "reqs";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onAnalyze(doc: DesignDocument) {
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await analyzeDocument(doc.id, {
      useLlm: true,
      analysisType: analysisType.value,
    });
    info.value = formatAnalysisNotice(out, `已分析「${doc.filename}」`);
    await reload();
    tabTouched.value = true;
    workspaceTab.value = "reqs";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onReanalyze(doc: DesignDocument) {
  if (
    !(await confirmDialog(
      `重新分析「${doc.filename}」（类型：${analysisType.value}）？将追加新的解析结果。`,
    ))
  ) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await reanalyzeDocument(doc.id, {
      useLlm: true,
      analysisType: analysisType.value,
    });
    const total = out.summary?.total_count ?? out.requirements?.length ?? 0;
    info.value = formatAnalysisNotice(out, `重新分析完成，共 ${total} 项`);
    await reload();
    tabTouched.value = true;
    workspaceTab.value = "reqs";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onPreview(doc: DesignDocument) {
  previewOpen.value = true;
  previewLoading.value = true;
  previewData.value = null;
  error.value = "";
  try {
    previewData.value = await previewDocument(doc.id);
  } catch (e: any) {
    error.value = e?.message || String(e);
    previewOpen.value = false;
  } finally {
    previewLoading.value = false;
  }
}

function closePreview() {
  previewOpen.value = false;
  previewData.value = null;
}

async function onRemove(doc: DesignDocument) {
  if (
    !(await confirmDialog(
      `删除文档「${doc.filename}」？\n已解析的需求不会自动删除。`,
      { danger: true },
    ))
  ) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    await deleteDocument(doc.id);
    info.value = `已删除文档「${doc.filename}」`;
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onBatchDeleteDocs(ids: string[]) {
  if (!ids.length) return;
  if (
    !(await confirmDialog(
      `批量删除 ${ids.length} 个文档？\n已解析的需求不会自动删除。`,
      { danger: true },
    ))
  ) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await batchDeleteDocuments(ids);
    info.value = out.message || `已删除 ${out.deleted_count ?? ids.length} 个文档`;
    docsList.value?.clearSelection();
    await reload();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onSaveReq(payload: {
  title: string;
  content: string;
  req_key: string;
  priority: string;
}) {
  if (!editingReq.value) return;
  if (!payload.title.trim()) {
    error.value = "标题不能为空";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await updateRequirement(editingReq.value.id, payload);
    editingReq.value = null;
    await reloadReqs();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onRemoveReq(item: Requirement) {
  if (
    !(await confirmDialog(`删除需求「${item.title}」？`, {
      danger: true,
    }))
  ) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    await deleteRequirement(item.id);
    info.value = `已删除需求「${item.title}」`;
    if (editingReq.value?.id === item.id) editingReq.value = null;
    await reloadReqs();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onBatchDeleteReqs(ids: string[]) {
  if (!ids.length) return;
  if (
    !(await confirmDialog(
      `批量删除 ${ids.length} 条需求？此操作不可撤销。`,
      { danger: true },
    ))
  ) return;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await batchDeleteRequirements(ids);
    info.value = out.message || `已删除 ${out.deleted_count ?? ids.length} 条需求`;
    reqsList.value?.clearSelection();
    if (editingReq.value && ids.includes(editingReq.value.id)) editingReq.value = null;
    await reloadReqs();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onGenerateFromReqs(items: Requirement[]) {
  const projectId = requireProject();
  if (!projectId) return;
  if (!items.length) {
    error.value = "请先勾选需求";
    return;
  }
  const text = items
    .map((r, i) => {
      const head = `[${r.req_key || `REQ-${i + 1}`}] ${r.title}`;
      const body = (r.content || "").trim();
      return body ? `${head}\n${body}` : head;
    })
    .join("\n\n");
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await generateLogicalCases({
      project_id: projectId,
      requirement_text: text,
      requirement_ids: items.map((r) => r.id),
      max_cases: Math.min(10, Math.max(3, items.length * 2)),
      use_rag: true,
    });
    const degraded = (out || []).some(
      (c) =>
        Boolean(c.generation_metadata?.degraded) ||
        String(c.generation_metadata?.generator || "").startsWith("heuristic"),
    );
    infoGotoCases.value = true;
    info.value = degraded
      ? `已根据 ${items.length} 条需求生成 ${out.length} 条草稿，但 AI 降级为启发式（degraded）——请重点审阅`
      : `已根据 ${items.length} 条需求生成 ${out.length} 条意图用例草稿`;
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onExportReqs() {
  busy.value = true;
  error.value = "";
  try {
    await exportRequirementsExcel({
      projectId: filterProjectId.value,
      sourceDocumentId: sourceDocFilter.value,
    });
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

function formatTime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
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
  <div class="page-stack docs-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>需求文档</h2>
        <p class="lede">上传需求文档，整理后可用来生成用例。</p>
      </div>
      <div class="page-hero-actions">
        <button type="button" class="small" :disabled="loading || busy" @click="onExportReqs">
          导出需求 Excel
        </button>
        <button type="button" class="ghost small" :disabled="loading || busy" @click="reload">
          刷新
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad">{{ error }}</div>
    <div
      v-else-if="info"
      class="msg info-row"
      :class="info.includes('degraded') || info.includes('降级') ? 'bad' : 'ok'"
    >
      <span>{{ info }}</span>
      <button
        v-if="infoGotoCases"
        type="button"
        class="small primary"
        @click="shell.activeTab = 'design-cases'"
      >
        查看意图用例
      </button>
    </div>

    <ProjectContextBanner />
    <ProjectReadonlyBanner />
    <DesignWorkflowBar page="docs" compact />

    <nav class="docs-tabs" aria-label="需求文档工作区">
      <button
        type="button"
        class="docs-tab"
        :class="{ active: workspaceTab === 'import' }"
        @click="selectWorkspace('import')"
      >
        <span class="docs-tab-idx">1</span>
        入库
      </button>
      <button
        type="button"
        class="docs-tab"
        :class="{ active: workspaceTab === 'docs' }"
        @click="selectWorkspace('docs')"
      >
        <span class="docs-tab-idx">2</span>
        文档
        <span class="docs-tab-count">{{ docsTotal }}</span>
      </button>
      <button
        type="button"
        class="docs-tab"
        :class="{ active: workspaceTab === 'reqs' }"
        @click="selectWorkspace('reqs')"
      >
        <span class="docs-tab-idx">3</span>
        需求条目
        <span class="docs-tab-count">{{ reqsTotal }}</span>
      </button>
    </nav>

    <!-- 1. 入库 -->
    <section v-if="workspaceTab === 'import'" class="surface-card docs-stage">
      <div class="stage-head">
        <div>
          <h3 class="stage-title">选择导入方式</h3>
          <p class="stage-sub">
            {{ canEdit ? "二选一即可，不必两种都走。" : "当前为只读成员，无法入库。" }}
          </p>
        </div>
      </div>
      <template v-if="canEdit">
        <div class="import-mode-tabs">
          <button
            type="button"
            class="mode-chip"
            :class="{ active: importMode === 'document' }"
            @click="importMode = 'document'"
          >
            上传原文并分析
          </button>
          <button
            type="button"
            class="mode-chip"
            :class="{ active: importMode === 'structured' }"
            @click="importMode = 'structured'"
          >
            结构化批量导入
          </button>
        </div>
        <DocsImportCard
          v-if="importMode === 'document'"
          ref="docsImport"
          bare
          :busy="busy"
          :disabled="!filterProjectId?.trim()"
          @import="onDocsImport"
        />
        <RequirementsImportCard
          v-else
          ref="reqsImport"
          bare
          :busy="busy"
          :disabled="!filterProjectId?.trim()"
          @import="onReqsImport"
        />
      </template>
      <div class="stage-foot">
        <button
          type="button"
          class="small"
          :disabled="!docsTotal && !reqsTotal"
          @click="selectWorkspace(reqsTotal ? 'reqs' : 'docs')"
        >
          已有内容？查看列表
        </button>
        <button type="button" class="small" @click="shell.activeTab = 'design-cases'">
          短需求去粘贴生成
        </button>
      </div>
    </section>

    <!-- 2. 文档 -->
    <div v-else-if="workspaceTab === 'docs'" class="docs-stage-stack">
      <section class="surface-card analysis-type-bar">
        <label class="field-label inline">
          列表分析类型
          <ApSelect
            size="compact"
            :disabled="busy"
            aria-label="列表分析类型"
            v-model="analysisType"
            :options="analysisTypes"
          />
        </label>
        <span class="meta-line">对下方「分析 / 重新分析」生效。</span>
        <button type="button" class="small" @click="selectWorkspace('import')">去入库</button>
      </section>

      <DocsListCard
        ref="docsList"
        v-model:q="docsQ"
        v-model:file-type="docsFileType"
        v-model:sort-by="docsSortBy"
        v-model:order="docsOrder"
        v-model:page="docsPage"
        v-model:page-size="docsPageSize"
        :docs="docs"
        :total="docsTotal"
        :loading="loading"
        :has-loaded="hasLoaded"
        :busy="busy"
        :readonly="!canEdit"
        @analyze="onAnalyze"
        @reanalyze="onReanalyze"
        @preview="onPreview"
        @remove="onRemove"
        @batch-delete="onBatchDeleteDocs"
        @open-import="openDocsImport"
      />

      <details
        class="fold-card surface-card"
        :open="historyOpen"
        @toggle="historyOpen = ($event.target as HTMLDetailsElement).open"
      >
        <summary class="fold-summary">
          <span>分析历史</span>
          <span class="fold-hint">{{ historyTotal ? `${historyTotal} 条记录` : "暂无记录" }}</span>
        </summary>
        <div v-if="!history.length && hasLoaded" class="empty-state compact">
          <p class="empty-desc">分析文档后会在此留下记录。</p>
        </div>
        <div v-else-if="history.length" class="table-wrap" style="margin-top: 0">
          <table>
            <thead>
              <tr>
                <th>文档</th>
                <th>类型</th>
                <th>需求数</th>
                <th>模式</th>
                <th>降级</th>
                <th>操作人</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in history" :key="h.id">
                <td>{{ docNameById[h.document_id] || h.document_id.slice(0, 8) }}</td>
                <td><span class="pill">{{ h.analysis_type }}</span></td>
                <td>{{ h.requirement_count }}</td>
                <td>{{ h.mode }}</td>
                <td>
                  <span
                    v-if="h.detail?.degraded || String(h.mode || '').includes('heuristic') || String(h.mode || '').includes(':failed')"
                    class="pill bad"
                    title="分析过程 AI 降级或子分析失败"
                  >
                    是
                  </span>
                  <span v-else class="meta-line">—</span>
                </td>
                <td>{{ h.created_by }}</td>
                <td class="meta-line">{{ formatTime(h.created_at) }}</td>
              </tr>
            </tbody>
          </table>
          <ListPager
            v-model:page="historyPage"
            v-model:page-size="historyPageSize"
            :total="historyTotal"
            :loading="loading"
          />
        </div>
      </details>
    </div>

    <!-- 3. 需求条目 -->
    <div v-else class="docs-stage-stack">
      <ReqEditForm
        :item="editingReq"
        :busy="busy"
        @save="onSaveReq"
        @cancel="editingReq = null"
      />

      <ReqsListCard
        ref="reqsList"
        v-model:q="reqsQ"
        v-model:priority="reqsPriority"
        v-model:source-document-id="sourceDocFilter"
        v-model:sort-by="reqsSortBy"
        v-model:order="reqsOrder"
        v-model:page="reqsPage"
        v-model:page-size="reqsPageSize"
        :reqs="reqs"
        :total="reqsTotal"
        :doc-options="docOptions"
        :loading="loading"
        :has-loaded="hasLoaded"
        :busy="busy"
        :readonly="!canEdit"
        @edit="editingReq = $event"
        @remove="onRemoveReq"
        @generate="onGenerateFromReqs"
        @batch-delete="onBatchDeleteReqs"
      />
    </div>

    <Teleport to="body">
      <div v-if="previewOpen" class="drawer-mask" @click="closePreview">
        <aside class="drawer preview-drawer" @click.stop>
          <header class="drawer-head">
            <div class="drawer-head-main">
              <h3 class="drawer-title">{{ previewData?.filename || "文档预览" }}</h3>
              <span v-if="previewData?.is_truncated" class="pill">内容已截断</span>
            </div>
            <button type="button" class="icon-btn" aria-label="关闭" @click="closePreview">✕</button>
          </header>
          <div class="drawer-body">
            <p v-if="previewLoading" class="meta-line">加载中…</p>
            <pre v-else-if="previewData" class="preview-content">{{ previewData.content }}</pre>
          </div>
        </aside>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.msg.bad,
.msg.ok {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  font-size: 0.85rem;
}
.msg.bad {
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
}
.msg.ok {
  background: var(--ok-soft-bg, var(--brand-soft));
  border: 1px solid var(--ok-soft-border, var(--line));
  color: var(--ok-soft-fg, var(--text));
}
.info-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
}
.docs-panel {
  width: 100%;
  min-width: 0;
}
.docs-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.15rem;
  padding: 0;
  border: none;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  width: 100%;
}
.docs-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.55rem 0.85rem;
  border: none;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  margin-bottom: -1px;
}
.docs-tab:hover {
  color: var(--text);
  background: var(--nav-hover, rgba(127, 127, 127, 0.06));
}
.docs-tab.active {
  color: var(--text);
  background: transparent;
  border-bottom-color: var(--accent);
  box-shadow: none;
}
.docs-tab-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.2rem;
  height: 1.2rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  font-size: 0.7rem;
}
.docs-tab.active .docs-tab-idx {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--on-accent, #fff);
}
.docs-tab-count {
  min-width: 1.25rem;
  padding: 0.05rem 0.35rem;
  border-radius: 999px;
  background: var(--chip-bg);
  border: 1px solid var(--line-soft);
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
}
.docs-stage {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  width: 100%;
  min-width: 0;
}
.docs-stage-stack {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.stage-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
}
.stage-title {
  margin: 0;
  font-size: 0.98rem;
}
.stage-sub {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  color: var(--muted);
}
.import-mode-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.mode-chip {
  margin: 0;
  padding: 0.4rem 0.7rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--control-bg);
  color: var(--muted);
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}
.mode-chip.active {
  border-color: var(--accent);
  background: var(--nav-active-bg);
  color: var(--text);
  font-weight: 600;
}
.stage-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding-top: 0.35rem;
  border-top: 1px solid var(--line-soft);
}
.field-label.inline {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0;
}
.field-label.inline .ap-select {
  min-width: 10rem;
}
.analysis-type-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}
.empty-state.compact {
  padding: 0.5rem 0;
}
.drawer-mask {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(720px, 92vw);
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  animation: drawer-in 0.18s ease-out;
}
@keyframes drawer-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.1rem;
  border-bottom: 1px solid var(--line);
}
.drawer-head-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}
.drawer-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.icon-btn {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.25rem 0.4rem;
  border-radius: 6px;
}
.icon-btn:hover {
  background: var(--chip-bg);
  color: var(--text);
}
.drawer-body {
  flex: 1;
  overflow: auto;
  padding: 1rem 1.1rem;
}
.preview-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.82rem;
  line-height: 1.55;
  color: var(--text);
  font-family: inherit;
}
</style>
