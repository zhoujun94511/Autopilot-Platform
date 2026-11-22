<script setup lang="ts">
defineOptions({ name: "DesignDashboardPanel" });

import { computed, onActivated, onMounted, ref, watch } from "vue";
import { useManualPageRefresh } from "../../composables/useManualPageRefresh";
import { apiErrorMessage, ensureFreshSession, type Artifact } from "../../api";
import { fetchAllArtifacts } from "../../api/opsLists";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { useAuthStore } from "../../stores/auth";
import { useAdminStore } from "../../stores/adminStore";
import { useCapabilities } from "../../composables/useCapabilities";
import {
  exportDesignBatchZip,
  exportDesignStatsCsv,
  fetchDesignStats,
  type DesignDomainStats,
} from "../../api/designStats";
import { pathForTab } from "../../router/tabs";
import { deriveDesignNextAction } from "./designWorkflowProgress";
import {
  SOLIDIFY_CLI_STEPS,
  VERIFIER_LIFECYCLE_STEPS,
  verifierHintFromStats,
} from "./automationLifecycleGuide";
import { auditActionLabel } from "../../utils/auditDisplay";
import { automationStatusLabel, reviewStatusLabel } from "../../utils/designStatusLabels";

const auth = useAuthStore();
const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterOrgId, filterProjectId, projects } = storeToRefs(projectsStore);
const { loggedIn, canManageUsers } = storeToRefs(auth);
const admin = useAdminStore();
const { auditFilter } = storeToRefs(admin);

const caps = useCapabilities();
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const stats = ref<DesignDomainStats | null>(null);
const artifacts = ref<Artifact[] | null>(null);
let loadGeneration = 0;

const projectName = computed(() => {
  const projectId = filterProjectId.value;
  return projects.value.find((project) => project.id === projectId)?.name || projectId;
});

async function load() {
  const generation = ++loadGeneration;
  if (!loggedIn.value) {
    loading.value = false;
    return;
  }
  const projectId = filterProjectId.value || undefined;
  loading.value = true;
  error.value = "";
  try {
    const ready = await ensureFreshSession();
    if (!ready || !loggedIn.value || generation !== loadGeneration) return;
    const result = await fetchDesignStats(projectId);
    if (generation !== loadGeneration) return;
    stats.value = result;
    if (!projectId) return;
    const projectArtifacts = await fetchAllArtifacts(projectId);
    if (generation === loadGeneration) artifacts.value = projectArtifacts;
  } catch (e: unknown) {
    if (generation === loadGeneration) error.value = apiErrorMessage(e);
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

async function onExportCsv() {
  busy.value = true;
  error.value = "";
  try {
    await exportDesignStatsCsv(filterProjectId.value || undefined);
    notice.value = "统计 CSV 已下载";
  } catch (e: unknown) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function onExportZip() {
  busy.value = true;
  error.value = "";
  try {
    await exportDesignBatchZip({
      projectId: filterProjectId.value || undefined,
      exportCases: true,
      exportRequirements: true,
      exportKnowledge: true,
      exportDocuments: false,
    });
    notice.value = "设计域 ZIP 已下载";
  } catch (e: unknown) {
    error.value = apiErrorMessage(e);
  } finally {
    busy.value = false;
  }
}

const nextAction = computed(() =>
  stats.value
    ? deriveDesignNextAction(stats.value, {
        artifacts: artifacts.value ?? [],
        projectId: filterProjectId.value || "",
      })
    : null,
);
const runReadiness = computed(() =>
  artifacts.value ? nextAction.value?.runReadiness ?? null : null,
);
const primaryAction = computed(() => {
  if (!filterProjectId.value || !nextAction.value) return null;
  if (!caps.canEditProject) return { tab: "design-cases", label: "查看用例" };
  if (nextAction.value.focus === "run" && !runReadiness.value) return null;
  return nextAction.value.primary;
});
const verifyHint = computed(() =>
  stats.value ? verifierHintFromStats(stats.value.by_automation_status) : "",
);
const showVerifyGuide = computed(() => {
  const by = stats.value?.by_automation_status || {};
  return (
    Number(by.PENDING_VERIFY || 0) > 0 ||
    Number(by.DEBUGGING || 0) > 0 ||
    Number(by.EXECUTABLE || 0) > 0
  );
});
const resources = [
  { key: "documents", label: "需求文档", tab: "design-docs" },
  { key: "requirements", label: "需求条目", tab: "design-docs" },
  { key: "logical_cases", label: "意图用例", tab: "design-cases" },
  { key: "knowledge", label: "知识条目", tab: "design-knowledge" },
] as const;
const reviewCounts = computed(() => Object.entries(stats.value?.by_review_status ?? {}));
const automationCounts = computed(() => Object.entries(stats.value?.by_automation_status ?? {}));
const tokens = computed(() => {
  const usage = stats.value?.tokens;
  if (!caps.canViewOpsBudget || !usage) return undefined;
  return usage.calls || usage.total_tokens ? usage : undefined;
});

function openDesignAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "design.";
  auditFilter.value.actor = "";
  shell.activeTab = "audit";
  void admin.refreshAudits();
}

let _skipActivateReload = false;
useManualPageRefresh("design-dashboard", load);
onMounted(() => {
  _skipActivateReload = true;
  void load();
});
onActivated(() => {
  if (_skipActivateReload) {
    _skipActivateReload = false;
    return;
  }
  void load();
});
watch([filterOrgId, filterProjectId, loggedIn], () => {
  stats.value = null;
  artifacts.value = null;
  error.value = "";
  notice.value = "";
  void load();
});
</script>

<template>
  <div class="page-stack design-dashboard">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>设计总览</h2>
      </div>
      <div class="page-hero-actions">
        <button type="button" :disabled="loading || busy" @click="load">
          {{ loading ? "刷新中…" : "刷新" }}
        </button>
        <details class="action-menu">
          <summary>导出</summary>
          <div class="action-menu-panel">
            <button type="button" :disabled="loading || busy" @click="onExportCsv">
              导出统计 CSV
            </button>
            <button type="button" :disabled="loading || busy" @click="onExportZip">
              批量 ZIP 导出
            </button>
          </div>
        </details>
      </div>
    </header>

    <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
    <p v-if="notice" class="msg ok" role="status">{{ notice }}</p>

    <div class="surface-card design-workspace" :aria-busy="loading">
      <div class="design-workspace-body">
        <section class="resource-section" aria-labelledby="design-resources-title">
          <header class="workspace-section-head">
            <h3 id="design-resources-title">设计资源</h3>
            <span v-if="projectName" class="workspace-scope" :title="projectName">
              {{ projectName }}
            </span>
          </header>
          <table aria-labelledby="design-resources-title">
            <thead>
              <tr>
                <th scope="col">资源</th>
                <th scope="col" class="resource-count">数量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="resource in resources" :key="resource.key">
                <th scope="row">
                  <RouterLink class="text-link" :to="pathForTab(resource.tab)">
                    {{ resource.label }}
                  </RouterLink>
                </th>
                <td class="resource-count">{{ stats?.[resource.key] ?? "—" }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="review-section" aria-labelledby="design-status-title">
          <header class="workspace-section-head">
            <h3 id="design-status-title">用例状态</h3>
            <RouterLink
              v-if="primaryAction"
              class="text-link"
              :to="pathForTab(primaryAction.tab)"
            >
              {{ primaryAction.label }}
            </RouterLink>
            <RouterLink
              v-else-if="!filterProjectId"
              class="text-link"
              :to="{ path: pathForTab('projects'), query: { section: 'collab' } }"
            >
              选项目
            </RouterLink>
          </header>

          <div v-if="reviewCounts.length || automationCounts.length" class="state-columns">
            <div v-if="reviewCounts.length">
              <h4>评审</h4>
              <dl class="state-list">
                <div v-for="[state, count] in reviewCounts" :key="state">
                  <dt>{{ reviewStatusLabel(state) }}</dt>
                  <dd>{{ count }}</dd>
                </div>
              </dl>
            </div>
            <div v-if="automationCounts.length">
              <h4>自动化</h4>
              <dl class="state-list">
                <div v-for="[state, count] in automationCounts" :key="state">
                  <dt>{{ automationStatusLabel(state) }}</dt>
                  <dd>{{ count }}</dd>
                </div>
              </dl>
            </div>
          </div>
          <p v-else class="workspace-empty">
            {{ loading ? "加载中…" : stats ? "暂无用例" : "统计暂不可用" }}
          </p>

          <div v-if="runReadiness && runReadiness.approvedCount > 0" class="run-ready-card">
            <div class="run-head">
              <h4>批跑准备</h4>
              <span v-if="runReadiness.missingArtifact" class="pill warn">待上传制品</span>
              <span v-else-if="!runReadiness.validArtifactCount" class="pill warn">待校验制品</span>
              <span v-else class="pill ok">可执行批跑</span>
            </div>
            <div class="run-meta">
              <span>审核通过 <strong>{{ runReadiness.approvedCount }}</strong></span>
              <RouterLink class="text-link" :to="pathForTab('artifacts')">
                工程制品 {{ runReadiness.artifactCount }}
              </RouterLink>
              <span v-if="runReadiness.artifactCount">清单有效 <strong>{{ runReadiness.validArtifactCount }}</strong></span>
            </div>
          </div>
        </section>
      </div>

      <details v-if="runReadiness?.missingArtifact" class="workspace-disclosure">
        <summary>在 IDE 上传工程制品</summary>
        <ol>
          <li v-for="step in runReadiness.ideUploadSteps" :key="step">{{ step }}</li>
        </ol>
      </details>
      <details v-if="showVerifyGuide" class="workspace-disclosure verify-lifecycle-card">
        <summary>首次运行与固化</summary>
        <p class="workspace-note">{{ verifyHint }}</p>
        <ol>
          <li v-for="step in VERIFIER_LIFECYCLE_STEPS" :key="step">{{ step }}</li>
        </ol>
        <ol>
          <li v-for="step in SOLIDIFY_CLI_STEPS" :key="step">{{ step }}</li>
        </ol>
      </details>
      <details v-if="tokens" class="workspace-disclosure">
        <summary>模型用量与审计</summary>
        <dl class="usage-list">
          <div><dt>日期</dt><dd>{{ tokens.day || "今日" }}</dd></div>
          <div><dt>调用次数</dt><dd>{{ tokens.calls ?? 0 }}</dd></div>
          <div v-if="(tokens.daily_budget ?? 0) > 0">
            <dt>预算剩余</dt><dd>{{ tokens.budget_remaining ?? "—" }} / {{ tokens.daily_budget }}</dd>
          </div>
          <div><dt>输入 Token</dt><dd>{{ tokens.prompt_tokens ?? 0 }}</dd></div>
          <div><dt>输出 Token</dt><dd>{{ tokens.completion_tokens ?? 0 }}</dd></div>
          <div><dt>缓存命中 Token</dt><dd>{{ tokens.cached_tokens ?? 0 }}</dd></div>
          <div><dt>缓存未命中 Token</dt><dd>{{ tokens.cache_miss_tokens ?? 0 }}</dd></div>
          <div><dt>缓存写入 Token</dt><dd>{{ tokens.cache_write_tokens ?? 0 }}</dd></div>
          <div><dt>Token 合计</dt><dd>{{ tokens.total_tokens ?? 0 }}</dd></div>
          <div>
            <dt>缓存命中率</dt>
            <dd>{{ tokens.cache_hit_rate == null ? "—" : `${Math.round(tokens.cache_hit_rate * 1000) / 10}%` }}</dd>
          </div>
          <div><dt>设计审计事件</dt><dd>{{ tokens.design_audit_events ?? 0 }}</dd></div>
        </dl>
        <p v-if="tokens.note" class="workspace-note">{{ tokens.note }}</p>
        <ul v-if="tokens.top_actions?.length" class="audit-actions">
          <li v-for="[action, count] in tokens.top_actions" :key="action">
            <span>{{ auditActionLabel(action) }}</span>
            <span>{{ count }}</span>
          </li>
        </ul>
        <button v-if="canManageUsers" type="button" class="small" @click="openDesignAudit">
          查看设计审计
        </button>
      </details>
    </div>
  </div>
</template>

<style scoped>
.design-workspace {
  padding: 0;
  overflow: hidden;
}

.design-workspace-body {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
}

.resource-section,
.review-section {
  min-width: 0;
}

.review-section {
  border-inline-start: 1px solid var(--line);
}

.workspace-section-head {
  min-height: 48px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--line);
}

.workspace-section-head h3,
.review-section h4 {
  margin: 0;
  font-weight: 600;
}

.workspace-section-head h3 {
  font-size: var(--font-size-body);
}

.workspace-scope {
  max-width: 50%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.resource-section :is(th, td) {
  padding-inline: 16px;
}

.resource-section tbody th {
  background: transparent;
  font-weight: 500;
  font-size: var(--font-size-body);
  border-color: var(--line-soft);
}

.resource-section tbody tr:last-child > * {
  border-bottom: 0;
}

.resource-count {
  text-align: end;
  font-variant-numeric: tabular-nums;
}

.text-link {
  color: var(--accent-text);
  font-size: var(--font-size-body);
  font-weight: 500;
  text-decoration: none;
}

.text-link:hover {
  text-decoration: underline;
}

.text-link:focus-visible,
.workspace-disclosure summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.state-columns,
.usage-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 24px;
  margin: 0;
  padding: 12px 16px;
}

.state-columns h4 {
  margin-bottom: 4px;
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.state-list {
  margin: 0;
}

.state-list > div,
.usage-list > div,
.audit-actions li {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding-block: 4px;
  font-variant-numeric: tabular-nums;
}

.state-list dd,
.usage-list dd {
  margin: 0;
  font-weight: 600;
}

.workspace-empty,
.workspace-note {
  margin: 0;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.workspace-empty {
  padding: 32px 24px;
  text-align: center;
}

.run-ready-card {
  margin: 0 16px;
  padding: 12px 0;
  border-top: 1px solid var(--line-soft);
}

.run-head,
.run-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  column-gap: 16px;
  row-gap: 4px;
}

.run-meta {
  margin-top: 8px;
  color: var(--muted);
}

.workspace-disclosure {
  border-top: 1px solid var(--line);
  padding: 0 16px;
}

.workspace-disclosure > summary {
  width: fit-content;
  min-height: 40px;
  display: list-item;
  align-content: center;
  cursor: pointer;
  font-weight: 600;
}

.workspace-disclosure[open] {
  padding-bottom: 12px;
}

.workspace-disclosure :is(ol, .audit-actions) {
  margin: 8px 0;
  color: var(--muted);
}

.workspace-disclosure ol {
  padding-left: 20px;
}

.usage-list {
  padding-inline: 0;
  max-width: 640px;
  gap: 0 24px;
}

.audit-actions {
  max-width: 420px;
  padding: 0;
}

@media (max-width: 960px) {
  .design-workspace-body {
    grid-template-columns: 1fr;
  }

  .review-section {
    border-inline-start: 0;
    border-top: 1px solid var(--line);
  }
}

@media (max-width: 480px) {
  .usage-list {
    grid-template-columns: 1fr;
  }
}
</style>
