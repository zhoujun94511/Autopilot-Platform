<script setup lang="ts">
defineOptions({ name: "DesignCasesPanel" });

import { computed, nextTick, onActivated, onDeactivated, onMounted, ref, watch } from "vue";
import { useManualPageRefresh } from "../../composables/useManualPageRefresh";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { useExecStore } from "../../stores/execution";
import { confirmDialog } from "../../composables/useNotify";
import {
  batchDeleteLogicalCases,
  batchGenerateLogicalCases,
  deleteLogicalCase,
  downloadApprovedBundle,
  downloadCasesTemplate,
  enqueueApprovedJob,
  exportLogicalCasesFile,
  generateLogicalCases,
  patchLogicalCase,
  queryLogicalCasesPage,
  regenerateLogicalCase,
  REVIEW_STATUS_OPTIONS,
  type EnqueueApprovedJobBody,
  type LogicalCase,
  type IntentStep,
} from "../../api/designCases";
import { fetchDesignStats, type DesignDomainStats } from "../../api/designStats";
import { DEFAULT_PAGE_SIZE } from "../../api/designList";
import { notify } from "../../composables/useNotify";
import AutomationStatusSelect from "./AutomationStatusSelect.vue";
import ApSelect from "../common/ApSelect.vue";
import DesignCaseGenerateCard from "./DesignCaseGenerateCard.vue";
import ListPager from "./ListPager.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import { useCapabilities } from "../../composables/useCapabilities";
import ProjectReadonlyBanner from "./ProjectReadonlyBanner.vue";
import CaseEditDrawer from "./CaseEditDrawer.vue";
import EnqueueRunConfigCard from "./EnqueueRunConfigCard.vue";
import IdeWebhookGuideCard from "./IdeWebhookGuideCard.vue";
import { AUTOMATION_QUICK_FILTERS, automationStatusHint } from "./automationStatusHints";
import { automationStatusLabel, reviewStatusLabel } from "../../utils/designStatusLabels";
import { parseUdids } from "../../composables/devicePick";
import { isDevicelessPlatform, isHttpPlatform, isWebPlatform, stripDevicelessSubmitPayload } from "../../composables/runTargetOptions";

const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId, filterOrgId } = storeToRefs(projectsStore);
const exec = useExecStore();
const { form } = storeToRefs(exec);

const caps = useCapabilities();
const canEdit = computed(() => Boolean(caps.canEditProject));

function blockWrite(action: string): boolean {
  if (!filterProjectId.value?.trim()) {
    error.value = "请先在顶栏选择项目";
    return true;
  }
  if (!canEdit.value) {
    error.value = `当前项目为只读，无法${action}`;
    return true;
  }
  return false;
}
const ctx = ref<{ missing: boolean } | null>(null);
const cases = ref<LogicalCase[]>([]);
const caseTotal = ref(0);
const casePage = ref(1);
const casePageSize = ref(DEFAULT_PAGE_SIZE);
const designStats = ref<DesignDomainStats | null>(null);
const loading = ref(false);
const hasLoaded = ref(false);
const universeEmpty = ref(false);
const listError = ref("");
const error = ref("");
const saveError = ref("");
const notice = ref("");
const noticeWarn = ref(false);
const busy = ref(false);
const generateCard = ref<{ clear: () => void } | null>(null);
const activeTool = ref<"generate" | "run" | null>(null);
const toolPanel = ref<HTMLElement | null>(null);
let toolOpener: HTMLElement | null = null;
const searchText = ref("");
const searchQuery = ref("");
const automationFilter = ref("");
const reviewFilter = ref("");
const selectedIds = ref<string[]>([]);
const editingCase = ref<LogicalCase | null>(null);

const hasActiveFilter = computed(() => Boolean(searchQuery.value || reviewFilter.value || automationFilter.value));

const automationCounts = computed(
  () => designStats.value?.by_automation_status || ({} as Record<string, number>),
);

const allVisibleSelected = computed(
  () =>
    cases.value.length > 0 &&
    cases.value.every((c) => selectedIds.value.includes(c.logical_case_id)),
);

/** 可入队 APPROVED 数（来自统计，不依赖当前页）。 */
const approvedEnqueueCount = computed(() => {
  const approvedTotal = Number(designStats.value?.by_review_status?.APPROVED || 0);
  if (selectedIds.value.length) {
    const sel = new Set(selectedIds.value);
    return cases.value.filter((c) => c.review_status === "APPROVED" && sel.has(c.logical_case_id))
      .length;
  }
  return approvedTotal;
});

const reviewLabel = reviewStatusLabel;
const automationLabel = automationStatusLabel;
const automationHint = automationStatusHint;

const riskClass: Record<string, string> = {
  low: "ok",
  medium: "warn",
  high: "bad",
};

/** P0/P1 需要能被一眼扫到，其余保持中性，避免整列彩虹。 */
const priorityClass: Record<string, string> = {
  P0: "bad",
  P1: "warn",
};

const riskLabelMap: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

function qualityText(row: LogicalCase): string {
  const quality = row.generation_metadata?.quality;
  const riskRaw = String(quality?.risk || "").trim().toLowerCase();
  const risk = riskLabelMap[riskRaw] || riskRaw;
  const score = quality?.score;
  if (score == null) return risk || "—";
  return risk ? `${risk} · ${score}` : String(score);
}

function stepSummary(row: LogicalCase): string {
  return (row.intent_steps || [])
    .map((s) => `${s.action} ${s.text || s.target || ""}`.trim())
    .join("\n");
}

function clearFilters() {
  searchText.value = "";
  searchQuery.value = "";
  reviewFilter.value = "";
  automationFilter.value = "";
  casePage.value = 1;
  if (universeEmpty.value) return;
  void loadCases();
}

function searchCases() {
  searchQuery.value = searchText.value.trim();
  casePage.value = 1;
  if (universeEmpty.value) return;
  void loadCases(false);
}

async function openTool(tool: "generate" | "run") {
  if (!canEdit.value) return;
  if (document.activeElement instanceof HTMLElement) toolOpener = document.activeElement;
  activeTool.value = tool;
  await nextTick();
  toolPanel.value?.scrollIntoView({ block: "nearest" });
  toolPanel.value?.focus({ preventScroll: true });
}

function closeTool() {
  activeTool.value = null;
  toolOpener?.focus();
}

let caseRequest = 0;
let statsRequest = 0;

async function loadDesignStats(projectId: string | undefined) {
  const request = ++statsRequest;
  try {
    const stats = await fetchDesignStats(projectId);
    if (request === statsRequest) designStats.value = stats;
  } catch {
    if (request === statsRequest) designStats.value = null;
  }
}

async function loadCases(refreshStats = true) {
  const request = ++caseRequest;
  const projectId = filterProjectId.value?.trim() || undefined;
  loading.value = true;
  listError.value = "";
  if (refreshStats) void loadDesignStats(projectId);
  try {
    const automationStatus = automationFilter.value || undefined;
    const page = await queryLogicalCasesPage({
      projectId,
      q: searchQuery.value || undefined,
      reviewStatus: reviewFilter.value || undefined,
      automationStatus,
      page: casePage.value,
      pageSize: casePageSize.value,
    });
    if (request !== caseRequest) return;
    const lastPage = Math.max(1, Math.ceil(page.total / page.page_size));
    if (!page.items.length && page.total > 0 && casePage.value > lastPage) {
      casePage.value = lastPage;
      await loadCases(false);
      return;
    }
    cases.value = page.items || [];
    caseTotal.value = page.total || 0;
    casePage.value = page.page || 1;
    casePageSize.value = page.page_size || casePageSize.value;
    if (caseTotal.value > 0) universeEmpty.value = false;
    else if (!hasActiveFilter.value) universeEmpty.value = true;
  } catch (e: any) {
    if (request === caseRequest) listError.value = e?.message || String(e);
  } finally {
    if (request === caseRequest) {
      loading.value = false;
      hasLoaded.value = true;
    }
  }
}

function onCasePageChange(p: number) {
  casePage.value = p;
  void loadCases(false);
}

function onCasePageSizeChange(size: number) {
  casePageSize.value = size;
  casePage.value = 1;
  void loadCases(false);
}

function onAutomationFilterChange(value: string) {
  automationFilter.value = value;
  if (universeEmpty.value) return;
  casePage.value = 1;
  void loadCases(false);
}

function onReviewFilterChange() {
  if (universeEmpty.value) return;
  casePage.value = 1;
  void loadCases(false);
}

async function onGenerate(payload: {
  text: string;
  useRag: boolean;
  autoApprove: boolean;
}) {
  if (blockWrite("生成用例")) return;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  if (!payload.text.trim()) {
    error.value = "请输入需求文本";
    return;
  }
  busy.value = true;
  error.value = "";
  notice.value = "";
  noticeWarn.value = false;
  try {
    const out = await generateLogicalCases({
      project_id: projectId,
      requirement_text: payload.text,
      max_cases: 5,
      use_rag: payload.useRag,
      auto_approve: payload.autoApprove,
    });
    generateCard.value?.clear();
    const degraded = (out || []).some(
      (c) =>
        Boolean(c.generation_metadata?.degraded) ||
        String(c.generation_metadata?.generator || "").startsWith("heuristic"),
    );
    const pendingVerify = (out || []).filter(
      (c) => c.automation_status === "PENDING_VERIFY",
    ).length;
    const dedupDropped = (out || []).reduce((n, c) => {
      const d = (c.generation_metadata as any)?.content_dedup;
      return n + Number(d?.dropped || 0);
    }, 0);
    noticeWarn.value = degraded;
    const bits = [
      degraded
        ? "已用规则生成草稿，请复核步骤"
        : "已生成意图用例草稿",
    ];
    if (pendingVerify > 0) bits.push(`${pendingVerify} 条进入待首次运行确认`);
    if (dedupDropped > 0) bits.push(`内容去重丢弃 ${dedupDropped} 条近似草稿`);
    notice.value = bits.join("；");
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onBatchGenerate(payload: {
  requirements: string[];
  caseCountPerReq: number;
  processMode: "sequential" | "parallel";
  useRag: boolean;
  autoApprove: boolean;
}) {
  if (blockWrite("生成用例")) return;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  if (!payload.requirements.length) {
    error.value = "请至少输入一条需求（每行一条）";
    return;
  }
  busy.value = true;
  error.value = "";
  notice.value = "";
  noticeWarn.value = false;
  try {
    const out = await batchGenerateLogicalCases({
      project_id: projectId,
      requirements: payload.requirements,
      case_count_per_req: payload.caseCountPerReq,
      process_mode: payload.processMode,
      use_rag: payload.useRag,
      auto_approve: payload.autoApprove,
    });
    generateCard.value?.clear();
    notice.value =
      out.message ||
      `批量生成完成，共 ${out.total_cases ?? payload.requirements.length} 条用例`;
    if (out.degraded) {
      noticeWarn.value = true;
      notice.value += "，含规则生成的草稿，请复核步骤";
    }
    const executed = String(out.summary?.executed_mode || "").toLowerCase();
    if (payload.processMode === "parallel") {
      if (executed === "parallel") {
        notice.value += "，已并行处理";
      } else {
        notice.value += `（请求并行，实际${out.summary?.note || "顺序执行"}）`;
        noticeWarn.value = true;
      }
    }
    const dedupDropped = (out.results || []).reduce((n: number, r: any) => {
      const cases = Array.isArray(r?.cases) ? r.cases : [];
      for (const c of cases) {
        n += Number(c?.generation_metadata?.content_dedup?.dropped || 0);
      }
      return n;
    }, 0);
    if (dedupDropped > 0) {
      notice.value += `（内容去重丢弃约 ${dedupDropped} 条近似草稿）`;
    }
    const pendingVerify = (out.results || []).reduce((n: number, r: any) => {
      const cases = Array.isArray(r?.cases) ? r.cases : [];
      return n + cases.filter((c: any) => c?.automation_status === "PENDING_VERIFY").length;
    }, 0);
    if (pendingVerify > 0) {
      notice.value += `（${pendingVerify} 条进入待首次运行确认）`;
    }
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function setReviewStatus(row: LogicalCase, status: string) {
  if (blockWrite("修改评审状态")) return;
  busy.value = true;
  error.value = "";
  try {
    await patchLogicalCase(row.logical_case_id, { review_status: status });
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onDelete(row: LogicalCase) {
  if (blockWrite("删除")) return;
  if (
    !(await confirmDialog(`删除用例「${row.title}」？此操作不可撤销。`, {
      danger: true,
    }))
  ) return;
  busy.value = true;
  error.value = "";
  try {
    await deleteLogicalCase(row.logical_case_id);
    selectedIds.value = selectedIds.value.filter((id) => id !== row.logical_case_id);
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onRegenerate(row: LogicalCase) {
  if (blockWrite("重新生成")) return;
  if (!(await confirmDialog(`基于「${row.title}」重新生成用例？原用例保留。`))) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  noticeWarn.value = false;
  try {
    const out = await regenerateLogicalCase(row.logical_case_id, { max_cases: 3, use_rag: true });
    const degraded = (out || []).some(
      (c) =>
        Boolean(c.generation_metadata?.degraded) ||
        String(c.generation_metadata?.generator || "").startsWith("heuristic"),
    );
    noticeWarn.value = degraded;
    notice.value = degraded
      ? `已用规则重新生成 ${out.length} 条用例，请复核步骤`
      : `已重新生成 ${out.length} 条用例`;
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

function toggleSelect(id: string, checked: boolean) {
  if (!canEdit.value) return;
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value = [...selectedIds.value, id];
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
}

function toggleSelectAll(checked: boolean) {
  if (!canEdit.value) return;
  if (checked) {
    const ids = new Set(selectedIds.value);
    for (const c of cases.value) ids.add(c.logical_case_id);
    selectedIds.value = [...ids];
  } else {
    const drop = new Set(cases.value.map((c) => c.logical_case_id));
    selectedIds.value = selectedIds.value.filter((id) => !drop.has(id));
  }
}

function openCase(row: LogicalCase) {
  saveError.value = "";
  editingCase.value = row;
}

function closeCase() {
  saveError.value = "";
  editingCase.value = null;
}

async function onSaveCase(payload: {
  title: string;
  priority: string;
  intent_steps: IntentStep[];
}) {
  const row = editingCase.value;
  if (!row || !canEdit.value || busy.value) return;
  busy.value = true;
  saveError.value = "";
  notice.value = "";
  try {
    await patchLogicalCase(row.logical_case_id, {
      title: payload.title,
      priority: payload.priority,
      intent_steps: payload.intent_steps,
      logical_steps: payload.intent_steps.map((s) => s.text || s.target || s.action),
    });
    if (editingCase.value?.logical_case_id !== row.logical_case_id) return;
    notice.value = "已保存用例";
    closeCase();
    await loadCases();
  } catch (e: any) {
    if (editingCase.value?.logical_case_id === row.logical_case_id) {
      saveError.value = e?.message || String(e);
    }
  } finally {
    busy.value = false;
  }
}

async function onBatchDelete() {
  if (blockWrite("删除")) return;
  if (!selectedIds.value.length) {
    error.value = "请先勾选要删除的用例";
    return;
  }
  if (
    !(await confirmDialog(
      `批量删除 ${selectedIds.value.length} 条用例？此操作不可撤销。`,
      { danger: true },
    ))
  ) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const out = await batchDeleteLogicalCases(selectedIds.value);
    notice.value = `已删除 ${out.deleted_count ?? 0} 条` + (out.failed_count ? `，失败 ${out.failed_count}` : "");
    selectedIds.value = [];
    await loadCases();
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onExport(format: "excel" | "csv" | "json") {
  busy.value = true;
  error.value = "";
  try {
    await exportLogicalCasesFile({
      projectId: filterProjectId.value,
      reviewStatus: reviewFilter.value,
      format,
      caseIds: selectedIds.value.length ? selectedIds.value : undefined,
    });
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onDownloadTemplate(format: "excel" | "csv") {
  busy.value = true;
  error.value = "";
  try {
    await downloadCasesTemplate(format);
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onDownloadApprovedBundle() {
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await downloadApprovedBundle(projectId);
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

/** O7：入队已通过用例并展示 Binding 软警告。需批跑表单已选制品与设备。 */
async function onEnqueueApproved() {
  if (blockWrite("入队")) return;
  const projectId = filterProjectId.value?.trim();
  if (!projectId) {
    error.value = "请先在顶栏选择项目";
    return;
  }
  const artifactId = String(form.value?.artifact_id || "").trim();
  if (!artifactId) {
    error.value = "请在下方的「批跑配置」中选择工程制品（含 bindings 更佳）";
    notice.value = "";
    noticeWarn.value = true;
    return;
  }
  const udids = parseUdids(String(form.value?.device_udids || ""));
  const platform = String(form.value?.platform || "android").toLowerCase() || "android";
  if (!udids.length && !isDevicelessPlatform(platform)) {
    error.value = "请在下方的「批跑配置」中勾选执行设备";
    return;
  }
  const ids = selectedIds.value.length > 0 ? [...selectedIds.value] : [];
  if (!selectedIds.value.length && approvedEnqueueCount.value <= 0) {
    error.value = "项目内没有可入队的已通过用例";
    return;
  }
  const eng = String(form.value?.web_engine || "selenium").trim().toLowerCase();
  const webEngine = eng === "playwright" ? "playwright" : "selenium";
  const envHint = isHttpPlatform(platform)
    ? ` / env ${String(form.value?.backend_mode || "auto")}`
    : isWebPlatform(platform)
      ? ` / ${webEngine}`
      : "";
  const deviceHint = isDevicelessPlatform(platform)
    ? (isHttpPlatform(platform) ? "（接口无需设备）" : "（Web 无需设备）")
    : (udids.join(", ") || "（未指定）");
  const ok = await confirmDialog(
    ids.length
      ? `将把已勾选的 ${ids.length} 条用例入队批跑？\n制品：${artifactId}\n平台：${platform}${envHint}\n设备：${deviceHint}`
      : `将把项目内全部已通过用例（${approvedEnqueueCount.value} 条）入队批跑？\n制品：${artifactId}\n平台：${platform}${envHint}\n设备：${deviceHint}`,
  );
  if (!ok) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  noticeWarn.value = false;
  try {
    const payload: EnqueueApprovedJobBody = {
      project_id: projectId,
      artifact_id: artifactId,
      logical_case_ids: ids,
      name: `approved-${projectId.slice(0, 8)}`,
      app_build_id: String(form.value?.app_build_id || "").trim(),
      platform,
      web_engine: platform === "web" ? webEngine : undefined,
      backend_mode: String(form.value?.backend_mode || "auto").trim() || "auto",
      wda_bundle: String(form.value?.wda_bundle || "").trim(),
      parallel: Boolean(form.value?.parallel) && !isDevicelessPlatform(platform),
      parallel_workers: Number(form.value?.parallel_workers) || 0,
      device_udids: udids,
      preferred_runner_id: form.value?.preferred_runner_id || null,
      webhook_url: String(form.value?.webhook_url || "").trim(),
    };
    stripDevicelessSubmitPayload(platform, payload as Record<string, unknown>);
    const job = await enqueueApprovedJob(payload);
    const warns = (job.warnings || []).filter((w) => String(w || "").trim());
    if (warns.length) {
      noticeWarn.value = true;
      notice.value = `已入队任务 ${job.id}（${warns.length} 条提示）：${warns.join("；")}`;
      for (const w of warns) notify(w, "info");
    } else {
      notice.value = `已入队任务 ${job.id}`;
    }
    shell.activeTab = "jobs";
    await shell.refreshScopes(["jobs", "devices"]);
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function onAutomationStatus(row: LogicalCase, status: string) {
  if (status === row.automation_status) return;
  const prev = row.automation_status;
  row.automation_status = status;
  busy.value = true;
  error.value = "";
  try {
    await patchLogicalCase(row.logical_case_id, { automation_status: status });
  } catch (e: any) {
    row.automation_status = prev;
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

let _skipActivateReload = false;
useManualPageRefresh("design-cases", loadCases);
onMounted(() => {
  _skipActivateReload = true;
  void loadCases();
});
onActivated(() => {
  if (_skipActivateReload) {
    _skipActivateReload = false;
    return;
  }
  void loadCases();
});
watch(
  [filterProjectId, filterOrgId],
  () => {
    selectedIds.value = [];
    activeTool.value = null;
    closeCase();
    cases.value = [];
    caseTotal.value = 0;
    designStats.value = null;
    hasLoaded.value = false;
    notice.value = "";
    error.value = "";
    automationFilter.value = "";
    casePage.value = 1;
    universeEmpty.value = false;
    void loadCases();
  },
);
onDeactivated(() => {
  closeCase();
  activeTool.value = null;
});
watch(canEdit, (ok) => {
  if (!ok) selectedIds.value = [];
});
</script>

<template>
  <section class="design-panel" aria-labelledby="cases-title">
    <header class="cases-header">
      <h2 id="cases-title">意图用例</h2>
      <div class="page-hero-actions">
        <details class="action-menu">
          <summary class="small">导出</summary>
          <div class="action-menu-panel">
            <button type="button" :disabled="loading || busy" @click="onExport('excel')">
              导出 Excel
            </button>
            <button type="button" :disabled="loading || busy" @click="onExport('csv')">
              导出 CSV
            </button>
            <button type="button" :disabled="loading || busy" @click="onExport('json')">
              导出 JSON
            </button>
            <div class="menu-sep"></div>
            <button type="button" :disabled="loading || busy" @click="onDownloadTemplate('excel')">
              下载模板
            </button>
            <button type="button" :disabled="loading || busy" @click="onDownloadApprovedBundle">
              已通过 JSON 包
            </button>
          </div>
        </details>
        <button type="button" class="ghost" :disabled="loading || busy" @click="loadCases()">
          刷新
        </button>
        <button
          v-if="canEdit"
          type="button"
          :disabled="busy"
          :aria-expanded="activeTool === 'run'"
          aria-controls="case-run-config"
          @click="openTool('run')"
        >
          批跑配置
        </button>
        <button
          v-if="canEdit"
          type="button"
          class="primary"
          :disabled="busy"
          :aria-expanded="activeTool === 'generate'"
          aria-controls="case-generate"
          @click="openTool('generate')"
        >
          生成用例
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad case-feedback" role="alert">{{ error }}</div>
    <div v-if="notice" class="msg case-feedback" :class="noticeWarn ? 'bad' : 'ok'" :role="noticeWarn ? 'alert' : 'status'">{{ notice }}</div>
    <ProjectContextBanner ref="ctx" class="case-feedback" />
    <ProjectReadonlyBanner class="case-feedback" />

    <section
      v-if="canEdit"
      v-show="activeTool"
      ref="toolPanel"
      class="case-tool-panel"
      tabindex="-1"
      :aria-label="activeTool === 'run' ? '批跑配置' : '生成用例'"
    >
      <button type="button" class="ghost small close-tool" :disabled="busy" @click="closeTool">
        收起
      </button>
      <div v-show="activeTool === 'generate'" id="case-generate" class="case-tool-content">
        <DesignCaseGenerateCard
          ref="generateCard"
          bare
          :busy="busy || !!ctx?.missing"
          @generate="onGenerate"
          @batch-generate="onBatchGenerate"
        />
        <button type="button" class="linkish" @click="shell.activeTab = 'design-docs'">
          从已导入的需求生成用例
        </button>
      </div>
      <div v-show="activeTool === 'run'" id="case-run-config" class="case-tool-content">
        <EnqueueRunConfigCard
          :approved-count="approvedEnqueueCount"
          :disabled="busy || !!ctx?.missing"
        />
        <div class="enqueue-action-row">
          <button
            type="button"
            class="primary"
            :disabled="loading || busy || !!ctx?.missing || !approvedEnqueueCount"
            @click="onEnqueueApproved"
          >
            入队已通过批跑
            <template v-if="approvedEnqueueCount">（{{ approvedEnqueueCount }} 条）</template>
          </button>
        </div>
        <IdeWebhookGuideCard :approved-count="approvedEnqueueCount" compact />
      </div>
    </section>

    <section class="case-list" aria-label="用例列表" :aria-busy="loading">
      <div class="case-filter-bar">
        <form class="list-search" role="search" @submit.prevent="searchCases">
          <input id="cases-search-input" v-model="searchText" name="cases-search" type="search" aria-label="搜索意图用例" placeholder="搜索用例名称或编号" />
          <button type="submit" :disabled="busy">搜索</button>
        </form>
        <label class="field-label inline">
          评审状态
          <ApSelect
            size="compact"
            :disabled="busy"
            aria-label="评审状态"
            :model-value="reviewFilter"
            :options="REVIEW_STATUS_OPTIONS"
            @update:model-value="reviewFilter = $event"
            @change="onReviewFilterChange"
          />
        </label>
        <button
          v-if="hasActiveFilter"
          type="button"
          class="linkish clear-filters"
          :disabled="busy"
          @click="clearFilters"
        >
          清空筛选
        </button>
      </div>
      <div class="case-status-bar">
        <div class="filter-chips" role="group" aria-label="按自动化状态筛选">
          <button
            v-for="chip in AUTOMATION_QUICK_FILTERS"
            :key="chip.value || 'all'"
            type="button"
            class="chip-btn"
            :class="{ active: automationFilter === chip.value }"
            :aria-pressed="automationFilter === chip.value"
            :title="chip.title"
            :disabled="busy"
            @click="onAutomationFilterChange(chip.value)"
          >
            {{ chip.label }}
            <span v-if="chip.value && automationCounts[chip.value]" class="chip-n">{{ automationCounts[chip.value] }}</span>
          </button>
        </div>
      </div>

      <div v-if="canEdit && selectedIds.length" class="bulk-bar" role="status">
        <span class="bulk-count">已选 {{ selectedIds.length }} 条</span>
        <div class="bulk-actions">
          <button type="button" class="small" :disabled="busy" @click="selectedIds = []">
            清空选择
          </button>
          <button
            v-if="canEdit"
            type="button"
            class="small danger"
            :disabled="loading || busy"
            @click="onBatchDelete"
          >
            删除所选
          </button>
        </div>
      </div>

      <p v-if="listError" class="msg bad list-error" role="alert">
        <span>{{ listError }}</span>
        <button type="button" class="small" :disabled="loading" @click="loadCases()">重试</button>
      </p>
      <p v-if="loading" class="result-meta" role="status">{{ cases.length ? '正在刷新用例…' : '正在加载用例…' }}</p>
      <div v-if="!listError && !cases.length && hasLoaded" class="empty-state cases-empty">
        <p class="empty-title">
          {{ hasActiveFilter ? "无匹配用例" : "暂无意图用例" }}
        </p>
        <div class="empty-actions">
          <button v-if="hasActiveFilter" type="button" class="primary small" @click="clearFilters">
            清空筛选
          </button>
          <template v-else-if="canEdit">
            <button type="button" class="small" @click="shell.activeTab = 'design-docs'">
              查看需求文档
            </button>
          </template>
        </div>
      </div>

      <div v-else-if="cases.length" class="table-wrap cases-table" tabindex="0" role="region" aria-label="意图用例列表">
          <table aria-label="意图用例">
          <colgroup>
            <col v-if="canEdit" class="col-check" />
            <col />
            <col class="col-priority" />
            <col class="col-review" />
            <col class="col-quality" />
            <col :class="canEdit ? 'col-automation' : 'col-automation-ro'" />
            <col class="col-steps" />
            <col v-if="canEdit" class="col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th v-if="canEdit">
                <input
                  type="checkbox"
                  aria-label="全选本页用例"
                  :checked="allVisibleSelected"
                  :disabled="busy || !cases.length"
                  @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
                />
              </th>
              <th>用例</th>
              <th>优先级</th>
              <th>评审</th>
              <th>质量</th>
              <th>自动化状态</th>
              <th class="num">步骤</th>
              <th v-if="canEdit">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in cases" :key="c.logical_case_id">
              <td v-if="canEdit">
                <input
                  type="checkbox"
                  :aria-label="`选择用例 ${c.title}`"
                  :checked="selectedIds.includes(c.logical_case_id)"
                  :disabled="busy"
                  @change="toggleSelect(c.logical_case_id, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td class="cell-case">
                <button
                  type="button"
                  class="title-btn"
                  :title="c.title"
                  @click="openCase(c)"
                >
                  {{ c.title }}
                </button>
                <div class="case-sub">
                  <code class="case-key">{{ c.case_key }}</code>
                  <span
                    v-if="
                      c.generation_metadata?.degraded ||
                      String(c.generation_metadata?.generator || '').startsWith('heuristic')
                    "
                    class="pill bad"
                    title="使用规则生成，请复核步骤"
                  >
                    规则生成
                  </span>
                  <span v-if="c.generation_metadata?.use_rag" class="meta-note">
                    知识命中 {{ c.generation_metadata?.rag?.hit_count ?? 0 }}
                  </span>
                  <span
                    v-if="c.intent_steps?.length"
                    class="intent-inline"
                    :title="stepSummary(c)"
                  >
                    <code>{{ c.intent_steps[0]?.action }}</code>
                    <span class="step-text">{{ c.intent_steps[0]?.text || c.intent_steps[0]?.target }}</span>
                    <span v-if="c.intent_steps.length > 1" class="more">
                      +{{ c.intent_steps.length - 1 }}
                    </span>
                  </span>
                </div>
              </td>
              <td>
                <span class="pill" :class="priorityClass[c.priority] || ''">{{ c.priority }}</span>
              </td>
              <td>
                <span
                  class="pill"
                  :class="{
                    ok: c.review_status === 'APPROVED',
                    bad: c.review_status === 'REJECTED',
                  }"
                >
                  {{ reviewLabel(c.review_status) }}
                </span>
              </td>
              <td>
                <span
                  class="pill"
                  :class="riskClass[c.generation_metadata?.quality?.risk || ''] || ''"
                  :title="(c.generation_metadata?.quality?.issues || []).join('; ')"
                >
                  {{ qualityText(c) }}
                </span>
              </td>
              <td>
                <AutomationStatusSelect
                  v-if="canEdit"
                  :model-value="c.automation_status"
                  :disabled="busy"
                  @change="(v) => onAutomationStatus(c, v)"
                />
                <span v-else class="pill" :title="automationHint(c.automation_status)">
                  {{ automationLabel(c.automation_status) }}
                </span>
              </td>
              <td class="num">{{ c.intent_steps?.length || c.logical_steps?.length || 0 }}</td>
              <td v-if="canEdit">
                <div class="row-actions">
                  <button
                    v-if="c.review_status !== 'APPROVED'"
                    type="button"
                    class="small"
                    :disabled="busy"
                    @click="setReviewStatus(c, 'APPROVED')"
                  >
                    通过
                  </button>
                  <details class="row-more">
                    <summary :aria-label="`${c.title} 的更多操作`">更多</summary>
                    <div class="row-more-actions">
                      <button type="button" class="small" :disabled="busy" @click="openCase(c)">编辑</button>
                      <button v-if="c.review_status !== 'REJECTED'" type="button" class="small" :disabled="busy" @click="setReviewStatus(c, 'REJECTED')">驳回</button>
                      <button type="button" class="small" :disabled="busy" @click="onRegenerate(c)">重新生成</button>
                      <button type="button" class="small danger" :disabled="busy" @click="onDelete(c)">删除</button>
                    </div>
                  </details>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <ListPager
        v-if="caseTotal > 0"
        class="cases-pager"
        :total="caseTotal"
        :page="casePage"
        :page-size="casePageSize"
        :loading="loading"
        :disabled="busy"
        @update:page="onCasePageChange"
        @update:page-size="onCasePageSizeChange"
      />
    </section>

    <CaseEditDrawer
      :item="editingCase"
      :readonly="!canEdit"
      :busy="busy"
      :save-error="saveError"
      @save="onSaveCase"
      @close="closeCase"
    />

  </section>
</template>

<style scoped>
.design-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
  border: none;
  border-radius: 0;
}
.cases-header {
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: var(--vben-radius-xl);
  box-shadow: var(--vben-shadow-card);
  padding: 14px 20px;
}
.case-list {
  background: var(--vben-bg-surface);
  border: 1px solid var(--vben-border);
  border-radius: var(--vben-radius-xl);
  box-shadow: var(--vben-shadow-card);
  overflow: hidden;
}
.cases-header,
.case-filter-bar,
.case-status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 16px 20px;
  border-bottom: 1px solid var(--line-soft);
}
.cases-header h2 {
  margin: 0;
  color: var(--text);
  font-size: var(--font-size-title);
  font-weight: 650;
}
.case-feedback {
  margin: 12px 20px;
}
.msg.bad {
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  background: var(--danger-soft-bg);
  border: 1px solid var(--danger-soft-border);
  color: var(--danger-soft-fg);
  font-size: 0.85rem;
}
.msg.ok {
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  background: var(--ok-soft-bg, var(--brand-soft));
  border: 1px solid var(--ok-soft-border, var(--line));
  color: var(--ok-soft-fg, var(--text));
  font-size: 0.85rem;
}
.case-list {
  min-width: 0;
}
.case-filter-bar {
  justify-content: flex-start;
  gap: var(--space-2) var(--space-4);
  min-width: 0;
  padding-block: 12px;
}
.case-status-bar {
  padding-block: 0;
}
.list-search {
  display: flex;
  flex: 0 1 280px;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.list-search input { min-width: 0; flex: 1 1 auto; }
.list-search button { flex: 0 0 auto; white-space: nowrap; }
.result-meta {
  margin: 0;
  padding: 10px 20px;
  color: var(--muted);
  font-size: var(--font-size-meta);
}
.list-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 12px 20px;
}
.field-label.inline {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--muted);
  margin: 0;
  white-space: nowrap;
}
.field-label.inline .ap-select {
  min-width: 8rem;
}
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  min-width: 0;
}
.clear-filters {
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  color: var(--accent);
  font: inherit;
  font-size: 0.78rem;
  cursor: pointer;
  text-decoration: underline;
}

.bulk-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem 0.85rem;
  padding: 8px 20px;
  border-bottom: 1px solid var(--line-soft);
  background: var(--brand-soft);
}
.bulk-count {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text);
}
.bulk-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.bulk-actions button {
  margin: 0;
}

/* —— 表格：固定状态列，用例列吃剩余宽度；标题/步骤单行截断，避免行内再堆一篇文档 —— */
.cases-table {
  margin: 0;
  border: 0;
  border-radius: 0;
}
.cases-table:focus-visible {
  outline-offset: -2px;
}
.cases-table table {
  table-layout: fixed;
  min-width: 940px;
}
.cases-table th,
.cases-table td {
  padding: var(--space-2) var(--space-3);
  vertical-align: middle;
}
.cases-table .col-check {
  width: 2.75rem;
}
.cases-table .col-priority {
  width: 5rem;
}
.cases-table .col-review {
  width: 7rem;
}
.cases-table .col-quality {
  width: 8rem;
}
.cases-table .col-automation {
  width: 11.5rem;
}
.cases-table .col-automation-ro {
  width: 7.5rem;
}
.cases-table .col-steps {
  width: 4.25rem;
}
.cases-table .col-actions {
  width: 124px;
}
.row-more { min-width: 44px; }
.row-more summary {
  color: var(--accent-text);
  padding: var(--space-1) 0;
  cursor: pointer;
  white-space: nowrap;
  font-size: var(--font-size-meta);
}
.row-more-actions {
  display: grid;
  justify-items: start;
  gap: var(--space-1);
  padding-block: var(--space-1);
}
.cases-table td:last-child .row-actions { align-items: flex-start; }
.cases-table th.num,
.cases-table td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.cell-case {
  min-width: 0;
}
.title-btn {
  appearance: none;
  display: block;
  width: 100%;
  max-width: 100%;
  margin: 0;
  padding: 0;
  min-height: 0;
  border: none;
  background: none;
  box-shadow: none;
  justify-content: flex-start;
  text-align: left;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font: inherit;
  font-weight: 600;
  font-size: 0.9rem;
  line-height: 1.4;
  color: var(--text);
  cursor: pointer;
}
.title-btn:hover {
  color: var(--accent-text, var(--accent));
  text-decoration: underline;
}
.case-sub {
  display: flex;
  align-items: center;
  gap: 0.4rem 0.55rem;
  margin-top: 0.28rem;
  min-width: 0;
  font-size: 0.75rem;
  color: var(--muted);
}
.case-key {
  flex-shrink: 0;
  font-size: 0.72rem;
  color: var(--mono);
}
.meta-note {
  flex-shrink: 0;
  white-space: nowrap;
}
.intent-inline {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}
.intent-inline code {
  flex-shrink: 0;
  font-size: 0.72rem;
  color: var(--mono);
}
.intent-inline .step-text {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.intent-inline .more {
  flex-shrink: 0;
  color: var(--muted);
}
.cases-table th:last-child,
.cases-table td:last-child {
  padding-inline-end: 20px;
}
.cases-pager {
  margin: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--line-soft);
}
.cases-empty {
  min-height: 148px;
  margin: 0;
  border: 0;
}
.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.75rem;
  justify-content: center;
}
.enqueue-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}
.case-tool-panel {
  display: grid;
  gap: var(--space-2);
  padding: 16px 20px;
  border-bottom: 1px solid var(--line-soft);
  background: var(--surface-secondary);
}
.close-tool {
  justify-self: end;
}
.case-tool-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow-wrap: anywhere;
}
.case-tool-content > .linkish {
  align-self: flex-start;
  padding-inline-start: 0;
}
.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0;
  padding: 0 6px;
  min-height: 43px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--font-size-body);
  cursor: pointer;
  transition: var(--transition);
}
.chip-btn:hover:not(:disabled) {
  color: var(--accent-text);
}
.chip-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.chip-btn.active {
  border-bottom-color: var(--accent);
  color: var(--accent-text, var(--text));
  font-weight: 600;
}
.chip-n {
  color: var(--muted);
  font-size: var(--font-size-meta);
  font-variant-numeric: tabular-nums;
}
@media (max-width: 720px) {
  .cases-header,
  .case-filter-bar,
  .case-status-bar,
  .case-tool-panel,
  .cases-pager {
    padding-inline: 12px;
  }
  .case-status-bar {
    gap: 0;
  }
  .list-search {
    flex-basis: 100%;
  }
}
</style>
