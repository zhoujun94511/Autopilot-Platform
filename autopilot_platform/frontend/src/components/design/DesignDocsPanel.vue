<script setup lang="ts">
defineOptions({ name: "DesignDocsPanel" });

import { computed, onActivated, onDeactivated, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { workspaceScopeVersion } from "../../composables/mcProjectsState";
import { useManualPageRefresh } from "../../composables/useManualPageRefresh";
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
import ProjectContextBanner from "./ProjectContextBanner.vue";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import ListPager from "./ListPager.vue";
import ApSelect from "../common/ApSelect.vue";
import ApModal from "../ApModal.vue";
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

type DocsWorkspaceTab = "docs" | "reqs";
type ImportMode = "document" | "structured";
const workspaceTab = ref<DocsWorkspaceTab>("docs");
const importOpen = ref(false);
const importMode = ref<ImportMode>("document");
const historyOpen = ref(false);

function selectWorkspace(tab: DocsWorkspaceTab) {
  workspaceTab.value = tab;
}

function openDocsImport() {
  if (!canEdit.value || busy.value) return;
  error.value = "";
  importMode.value = "document";
  importOpen.value = true;
}

onDeactivated(() => {
  importOpen.value = false;
  closePreview();
});

const docNameById = computed(() => {
  const m: Record<string, string> = {};
  for (const d of docOptions.value) m[d.id] = d.filename;
  for (const d of docs.value) m[d.id] = d.filename;
  return m;
});

function makeScopedReader() {
  let requestId = 0;
  return async <T>(request: () => Promise<T>, apply: (result: T) => void) => {
    if (!filterProjectId.value.trim()) return;
    const scope = workspaceScopeVersion.value;
    const id = ++requestId;
    const current = () => scope === workspaceScopeVersion.value && id === requestId;
    try {
      const result = await request();
      if (current()) apply(result);
    } catch (cause) {
      if (current()) throw cause;
    }
  };
}

const readDocOptions = makeScopedReader();
const readDocs = makeScopedReader();
const readReqs = makeScopedReader();
const readHistory = makeScopedReader();
let reloadRequestId = 0;
let previewRequestId = 0;

async function reloadDocOptions() {
  const pid = filterProjectId.value?.trim();
  await readDocOptions(() => listDocuments(pid), (items) => {
    docOptions.value = items;
  });
}

async function reloadDocs() {
  const pid = filterProjectId.value?.trim();
  await readDocs(() => listDocumentsPage({
    projectId: pid,
    q: docsQDebounced.value,
    fileType: docsFileType.value || undefined,
    sortBy: docsSortBy.value,
    order: docsOrder.value,
    page: docsPage.value,
    pageSize: docsPageSize.value,
  }), (out) => {
    docs.value = out.items;
    docsTotal.value = out.total;
    docsPageSize.value = out.page_size;
    docsPage.value = out.items.length === 0 && out.total > 0 && out.page > 1
      ? Math.max(1, Math.ceil(out.total / out.page_size))
      : out.page;
  });
}

async function reloadReqs() {
  const pid = filterProjectId.value?.trim();
  await readReqs(() => listRequirementsPage({
    projectId: pid,
    sourceDocumentId: sourceDocFilter.value.trim() || undefined,
    q: reqsQDebounced.value,
    priority: reqsPriority.value || undefined,
    sortBy: reqsSortBy.value,
    order: reqsOrder.value,
    page: reqsPage.value,
    pageSize: reqsPageSize.value,
  }), (out) => {
    reqs.value = out.items;
    reqsTotal.value = out.total;
    reqsPageSize.value = out.page_size;
    reqsPage.value = out.items.length === 0 && out.total > 0 && out.page > 1
      ? Math.max(1, Math.ceil(out.total / out.page_size))
      : out.page;
  });
}

async function reloadHistory() {
  await readHistory(() => listAnalysisHistoryPage({
    projectId: filterProjectId.value?.trim(),
    documentId: sourceDocFilter.value.trim() || undefined,
    page: historyPage.value,
    pageSize: historyPageSize.value,
  }), (out) => {
    history.value = out.items;
    historyTotal.value = out.total;
    historyPageSize.value = out.page_size;
    historyPage.value = out.items.length === 0 && out.total > 0 && out.page > 1
      ? Math.max(1, Math.ceil(out.total / out.page_size))
      : out.page;
  });
}

async function reload() {
  if (!filterProjectId.value.trim()) return;
  const scope = workspaceScopeVersion.value;
  const id = ++reloadRequestId;
  const current = () => scope === workspaceScopeVersion.value && id === reloadRequestId;
  loading.value = true;
  error.value = "";
  try {
    await Promise.all([reloadDocOptions(), reloadDocs(), reloadReqs(), reloadHistory()]);
  } catch (e: any) {
    if (current()) error.value = e?.message || String(e);
  } finally {
    if (current()) {
      loading.value = false;
      hasLoaded.value = true;
    }
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
  workspaceScopeVersion,
  () => {
    docsPage.value = 1;
    reqsPage.value = 1;
    historyPage.value = 1;
    docs.value = [];
    reqs.value = [];
    history.value = [];
    docOptions.value = [];
    docsTotal.value = 0;
    reqsTotal.value = 0;
    historyTotal.value = 0;
    sourceDocFilter.value = "";
    hasLoaded.value = false;
    loading.value = false;
    error.value = "";
    info.value = "";
    infoGotoCases.value = false;
    editingReq.value = null;
    importOpen.value = false;
    docsList.value?.clearSelection();
    reqsList.value?.clearSelection();
    docsImport.value?.clearFiles();
    reqsImport.value?.clearFiles();
    closePreview();
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
  if (busy.value) return;
  const projectId = requireProject();
  if (!projectId) return;
  const scope = workspaceScopeVersion.value;
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
    if (scope !== workspaceScopeVersion.value) return;
    const base = out.message || "文档导入完成";
    info.value =
      out.degraded || out.summary?.degraded
        ? `${base}${base.includes("degraded") ? "" : " ⚠ AI 已降级为启发式——请人工审阅"}`
        : base;
    docsImport.value?.clearFiles();
    importOpen.value = false;
    await reload();
    if (scope === workspaceScopeVersion.value) {
      workspaceTab.value = reqsTotal.value > 0 ? "reqs" : "docs";
    }
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onReqsImport(payload: { files: File[] }) {
  if (busy.value) return;
  const projectId = requireProject();
  if (!projectId) return;
  const scope = workspaceScopeVersion.value;
  busy.value = true;
  error.value = "";
  info.value = "";
  infoGotoCases.value = false;
  try {
    const out = await importRequirementFiles({ projectId, files: payload.files });
    if (scope !== workspaceScopeVersion.value) return;
    info.value = out.message || "需求导入完成";
    reqsImport.value?.clearFiles();
    importOpen.value = false;
    await reload();
    if (scope === workspaceScopeVersion.value) workspaceTab.value = "reqs";
  } catch (e: any) {
    if (scope === workspaceScopeVersion.value) error.value = e?.message || String(e);
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
    workspaceTab.value = "reqs";
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onPreview(doc: DesignDocument) {
  const scope = workspaceScopeVersion.value;
  const id = ++previewRequestId;
  const current = () => scope === workspaceScopeVersion.value && id === previewRequestId;
  previewOpen.value = true;
  previewLoading.value = true;
  previewData.value = null;
  error.value = "";
  try {
    const preview = await previewDocument(doc.id);
    if (current()) previewData.value = preview;
  } catch (e: any) {
    if (current()) {
      error.value = e?.message || String(e);
      previewOpen.value = false;
    }
  } finally {
    if (current()) previewLoading.value = false;
  }
}

function closePreview() {
  previewRequestId += 1;
  previewOpen.value = false;
  previewLoading.value = false;
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
useManualPageRefresh("design-docs", reload);
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
  <div class="page-stack data-page docs-panel">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>需求文档</h2>
      </div>
      <div class="page-hero-actions">
        <button v-if="canEdit" type="button" class="ghost small" @click="shell.activeTab = 'design-cases'">
          生成意图用例
        </button>
        <button type="button" class="small" :disabled="loading || busy" @click="onExportReqs">
          导出需求 Excel
        </button>
        <button type="button" class="ghost small" :disabled="loading || busy" @click="reload">
          刷新
        </button>
        <button
          v-if="canEdit"
          type="button"
          class="primary small"
          :disabled="busy"
          @click="openDocsImport"
        >
          导入
        </button>
      </div>
    </header>

    <div v-if="error && !importOpen" class="msg bad" role="alert">{{ error }}</div>
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
    <nav class="docs-tabs" aria-label="需求文档工作区">
      <button
        type="button"
        class="docs-tab"
        :class="{ active: workspaceTab === 'docs' }"
        :aria-pressed="workspaceTab === 'docs'"
        @click="selectWorkspace('docs')"
      >
        文档
        <span class="docs-tab-count">{{ docsTotal }}</span>
      </button>
      <button
        type="button"
        class="docs-tab"
        :class="{ active: workspaceTab === 'reqs' }"
        :aria-pressed="workspaceTab === 'reqs'"
        @click="selectWorkspace('reqs')"
      >
        需求条目
        <span class="docs-tab-count">{{ reqsTotal }}</span>
      </button>
    </nav>

    <ApModal
      v-if="importOpen && canEdit"
      title="导入需求文档"
      variant="drawer"
      :close-on-backdrop="false"
      :close-on-esc="!busy"
      @close="importOpen = false"
    >
      <div class="docs-stage">
        <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
        <div class="import-mode-tabs" role="group" aria-label="导入方式">
          <button
            type="button"
            class="mode-chip"
            :class="{ active: importMode === 'document' }"
            :aria-pressed="importMode === 'document'"
            :disabled="busy"
            @click="importMode = 'document'"
          >
            上传原文并分析
          </button>
          <button
            type="button"
            class="mode-chip"
            :class="{ active: importMode === 'structured' }"
            :aria-pressed="importMode === 'structured'"
            :disabled="busy"
            @click="importMode = 'structured'"
          >
            结构化批量导入
          </button>
        </div>
        <DocsImportCard
          v-show="importMode === 'document'"
          ref="docsImport"
          bare
          :busy="busy"
          :disabled="!filterProjectId?.trim()"
          @import="onDocsImport"
        />
        <RequirementsImportCard
          v-show="importMode === 'structured'"
          ref="reqsImport"
          bare
          :busy="busy"
          :disabled="!filterProjectId?.trim()"
          @import="onReqsImport"
        />
      </div>
      <template #actions>
        <button type="button" :disabled="busy" @click="importOpen = false">关闭</button>
      </template>
    </ApModal>

    <div v-if="workspaceTab === 'docs'" class="docs-stage-stack">
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
      >
        <template v-if="canEdit" #analysis-filter>
          <label class="field-label inline">
            分析类型
            <ApSelect
              size="toolbar"
              :disabled="busy"
              aria-label="分析类型"
              v-model="analysisType"
              :options="analysisTypes"
            />
          </label>
        </template>
      </DocsListCard>

      <details
        class="fold-card docs-history"
        :open="historyOpen"
        @toggle="historyOpen = ($event.target as HTMLDetailsElement).open"
      >
        <summary class="fold-summary">
          <span>分析历史</span>
          <span class="fold-hint">{{ historyTotal ? `${historyTotal} 条记录` : "暂无记录" }}</span>
        </summary>
        <div v-if="!history.length && hasLoaded" class="empty-state compact">
          <p class="empty-desc">暂无分析记录</p>
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

    <ApModal
      v-if="previewOpen"
      :title="previewData?.filename || '文档预览'"
      variant="drawer"
      wide
      @close="closePreview"
    >
      <p v-if="previewLoading" class="meta-line" role="status">加载中…</p>
      <template v-else-if="previewData">
        <p v-if="previewData.is_truncated" class="meta-line">预览未包含文档末尾。</p>
        <pre class="preview-content">{{ previewData.content }}</pre>
      </template>
      <template #actions>
        <button type="button" @click="closePreview">关闭</button>
      </template>
    </ApModal>
  </div>
</template>

<style scoped>
.msg.bad,
.msg.ok {
  margin: 0;
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
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
.docs-tab-count {
  min-width: 1.25rem;
  padding: 0.05rem 0.35rem;
  border-radius: var(--radius-sm);
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
.import-mode-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.mode-chip {
  margin: 0;
  padding: 0.4rem 0.7rem;
  border-radius: var(--radius-sm);
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
.docs-history {
  border-top: 1px solid var(--line-soft);
}
.empty-state.compact {
  padding: 0.5rem 0;
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
