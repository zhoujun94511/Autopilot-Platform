<script setup lang="ts">
defineOptions({ name: "DesignDashboardPanel" });

import { computed, onActivated, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../../api";
import { storeToRefs } from "pinia";
import { useProjectsStore } from "../../stores/projectsStore";
import { useShellStore } from "../../stores/shellStore";
import { useAuthStore } from "../../stores/auth";
import { useExecStore } from "../../stores/execution";
import { useAdminStore } from "../../stores/adminStore";
import { useCapabilities } from "../../composables/useCapabilities";
import {
  exportDesignBatchZip,
  exportDesignStatsCsv,
  fetchDesignStats,
  type DesignDomainStats,
} from "../../api/designStats";
import DesignWorkflowBar from "./DesignWorkflowBar.vue";
import ProjectContextBanner from "./ProjectContextBanner.vue";
import { deriveDesignNextAction } from "./designWorkflowProgress";
import {
  SOLIDIFY_CLI_STEPS,
  VERIFIER_LIFECYCLE_STEPS,
  verifierHintFromStats,
} from "./automationLifecycleGuide";
import { auditActionLabel } from "../../utils/auditDisplay";

const auth = useAuthStore();
const shell = useShellStore();
const projectsStore = useProjectsStore();
const { filterProjectId } = storeToRefs(projectsStore);
const { loggedIn, canManageUsers } = storeToRefs(auth);
const exec = useExecStore();
const { artifacts } = storeToRefs(exec);
const admin = useAdminStore();
const { auditFilter } = storeToRefs(admin);

const caps = useCapabilities();
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const stats = ref<DesignDomainStats | null>(null);

async function load() {
  if (!loggedIn.value) {
    stats.value = null;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const ready = await ensureFreshSession();
    if (!ready || !loggedIn.value) {
      stats.value = null;
      return;
    }
    stats.value = await fetchDesignStats(filterProjectId.value || undefined);
    await shell.refreshScopes(["artifacts"]);
  } catch (e: any) {
    error.value = e?.message || String(e);
    stats.value = null;
  } finally {
    loading.value = false;
  }
}

async function onExportCsv() {
  busy.value = true;
  error.value = "";
  try {
    await exportDesignStatsCsv(filterProjectId.value || undefined);
    notice.value = "统计 CSV 已下载";
  } catch (e: any) {
    error.value = e?.message || String(e);
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
  } catch (e: any) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}

function go(tab: string) {
  shell.activeTab = tab;
}

const nextAction = computed(() =>
  stats.value
    ? deriveDesignNextAction(stats.value, {
        artifacts: artifacts.value,
        projectId: filterProjectId.value || "",
      })
    : null,
);
const runReadiness = computed(() => nextAction.value?.runReadiness ?? null);
const verifyHint = computed(() =>
  stats.value ? verifierHintFromStats(stats.value.by_automation_status) : "",
);
const showVerifyCard = computed(() => {
  const by = stats.value?.by_automation_status || {};
  return (
    Number(by.PENDING_VERIFY || 0) > 0 ||
    Number(by.DEBUGGING || 0) > 0 ||
    Number(by.EXECUTABLE || 0) > 0
  );
});
/** 规模全 0 时不展示空网格，避免「四个 0」壳 */
const showScaleCard = computed(() => {
  const s = stats.value;
  if (!s) return false;
  return (
    Number(s.requirements || 0) +
      Number(s.logical_cases || 0) +
      Number(s.knowledge || 0) +
      Number(s.documents || 0) >
    0
  );
});
const showTokenCard = computed(() => {
  if (!caps.canViewOpsBudget || !stats.value?.tokens) return false;
  const t = stats.value.tokens;
  return Number(t.calls || 0) > 0 || Number(t.total_tokens || 0) > 0;
});
const nextHint = computed(() => nextAction.value?.hint || "");

function openDesignAudit() {
  if (!canManageUsers.value) return;
  auditFilter.value.action = "design.";
  auditFilter.value.actor = "";
  shell.activeTab = "audit";
  void admin.refreshAudits();
}

let _skipActivateReload = false;
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
watch(() => filterProjectId.value, () => void load());
watch(
  () => loggedIn.value,
  (ok) => {
    if (ok) void load();
    else {
      stats.value = null;
      error.value = "";
    }
  },
);
</script>

<template>
  <div class="page-stack design-dashboard">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h2>设计总览</h2>
        <p class="lede">从需求生成用例。完整材料放到需求文档；知识库可选。</p>
      </div>
      <div class="page-hero-actions">
        <details class="action-menu">
          <summary class="small">导出</summary>
          <div class="action-menu-panel">
            <button type="button" :disabled="loading || busy" @click="onExportCsv">
              导出统计 CSV
            </button>
            <button type="button" :disabled="loading || busy" @click="onExportZip">
              批量 ZIP 导出
            </button>
          </div>
        </details>
        <button type="button" class="ghost small" :disabled="loading || busy" @click="load">
          刷新
        </button>
      </div>
    </header>

    <div v-if="error" class="msg bad">{{ error }}</div>
    <div v-if="notice" class="msg ok">{{ notice }}</div>

    <ProjectContextBanner show-when-ready />
    <DesignWorkflowBar page="dashboard" />

    <div class="dash-grid">
    <section v-if="nextAction" class="surface-card next-card dash-span">
      <h3>建议下一步</h3>
      <p class="meta-line">{{ nextHint }}</p>
      <div class="next-actions">
        <button type="button" class="primary small" @click="go(nextAction.primary.tab)">
          {{ nextAction.primary.label }}
        </button>
        <button
          v-if="(stats?.documents || 0) > 0 || (stats?.requirements || 0) > 0"
          type="button"
          class="small"
          @click="go('design-docs')"
        >
          有材料：需求文档
        </button>
        <button
          v-if="(stats?.knowledge || 0) > 0"
          type="button"
          class="small"
          @click="go('design-knowledge')"
        >
          可选：知识库
        </button>
      </div>
    </section>

    <section v-if="runReadiness && runReadiness.approvedCount > 0" class="surface-card run-ready-card dash-span">
      <h3>可以远程跑了</h3>
      <p class="meta-line">{{ runReadiness.hint }}</p>
      <div class="stat-grid mini">
        <div class="stat-cell">
          <span class="stat-n">{{ runReadiness.approvedCount }}</span>
          <span class="stat-l">已通过</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ runReadiness.artifactCount }}</span>
          <span class="stat-l">工程制品</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ runReadiness.validArtifactCount }}</span>
          <span class="stat-l">清单有效</span>
        </div>
      </div>
      <details v-if="runReadiness.missingArtifact" class="ide-guide">
        <summary>AutoPilot IDE 上传制品步骤</summary>
        <ol>
          <li v-for="(step, i) in runReadiness.ideUploadSteps" :key="i">{{ step }}</li>
        </ol>
      </details>
      <div class="next-actions">
        <button type="button" class="primary small" @click="go('design-cases')">
          {{ nextAction?.primary.label || "去意图用例" }}
        </button>
        <button type="button" class="small" @click="go('artifacts')">
          查看制品列表
        </button>
      </div>
    </section>

    <section v-if="showVerifyCard" class="surface-card verify-lifecycle-card">
      <h3>首次运行与固化</h3>
      <p class="meta-line">{{ verifyHint }}</p>
      <details>
        <summary>验证状态流转</summary>
        <ol>
          <li v-for="(step, i) in VERIFIER_LIFECYCLE_STEPS" :key="'v' + i">{{ step }}</li>
        </ol>
      </details>
      <details>
        <summary>在本机把稳定步骤固化成普通关键字</summary>
        <ol>
          <li v-for="(step, i) in SOLIDIFY_CLI_STEPS" :key="'s' + i">{{ step }}</li>
        </ol>
      </details>
    </section>

    <section v-if="showScaleCard && stats" class="surface-card">
      <h3>规模</h3>
      <div class="stat-grid">
        <button
          v-if="(stats.requirements || 0) > 0"
          type="button"
          class="stat-cell clickable"
          @click="go('design-docs')"
        >
          <span class="stat-n">{{ stats.requirements }}</span>
          <span class="stat-l">需求</span>
        </button>
        <button
          v-if="(stats.logical_cases || 0) > 0"
          type="button"
          class="stat-cell clickable"
          @click="go('design-cases')"
        >
          <span class="stat-n">{{ stats.logical_cases }}</span>
          <span class="stat-l">意图用例</span>
        </button>
        <button
          v-if="(stats.knowledge || 0) > 0"
          type="button"
          class="stat-cell clickable"
          @click="go('design-knowledge')"
        >
          <span class="stat-n">{{ stats.knowledge }}</span>
          <span class="stat-l">知识</span>
        </button>
        <button
          v-if="(stats.documents || 0) > 0"
          type="button"
          class="stat-cell clickable"
          @click="go('design-docs')"
        >
          <span class="stat-n">{{ stats.documents }}</span>
          <span class="stat-l">文档</span>
        </button>
      </div>
    </section>

    <section v-if="showTokenCard && stats?.tokens" class="surface-card">
      <h3>用量</h3>
      <p class="meta-line">
        {{ stats.tokens.day || "今日" }} · 调用 {{ stats.tokens.calls ?? 0 }} 次
        <template v-if="(stats.tokens.daily_budget ?? 0) > 0">
          · 预算剩余 {{ stats.tokens.budget_remaining ?? "—" }} /
          {{ stats.tokens.daily_budget }}
        </template>
      </p>
      <div class="stat-grid">
        <div class="stat-cell">
          <span class="stat-n">{{ stats.tokens.prompt_tokens ?? 0 }}</span>
          <span class="stat-l">输入</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ stats.tokens.completion_tokens ?? 0 }}</span>
          <span class="stat-l">输出</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ stats.tokens.cached_tokens ?? 0 }}</span>
          <span class="stat-l">缓存命中</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ stats.tokens.total_tokens ?? 0 }}</span>
          <span class="stat-l">合计</span>
        </div>
      </div>
      <p class="meta-line">
        命中率：
        {{
          stats.tokens.cache_hit_rate == null
            ? "—"
            : `${Math.round(Number(stats.tokens.cache_hit_rate) * 1000) / 10}%`
        }}
        · miss {{ stats.tokens.cache_miss_tokens ?? 0 }}
        · write {{ stats.tokens.cache_write_tokens ?? 0 }}
      </p>
      <p class="meta-line">{{ stats.tokens.note }}</p>
      <p class="meta-line">
        设计审计事件：{{ stats.tokens.design_audit_events ?? 0 }}
        <button
          v-if="canManageUsers"
          type="button"
          class="linkish inline"
          @click="openDesignAudit"
        >
          在审计页查看
        </button>
      </p>
      <ul v-if="stats.tokens.top_actions?.length" class="action-list">
        <li v-for="([act, n], i) in stats.tokens.top_actions" :key="i">
          <span>{{ auditActionLabel(act) }}</span>
          <span class="action-count">{{ n }}</span>
        </li>
      </ul>
    </section>

    <div v-else-if="loading" class="surface-card dash-span">
      <p class="meta-line">加载中…</p>
    </div>
    </div>
  </div>
</template>

<style scoped>
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
.design-dashboard {
  width: 100%;
  min-width: 0;
}
.dash-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
  align-items: start;
  width: 100%;
}
.dash-span {
  grid-column: 1 / -1;
}
.next-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.65rem;
}
.stat-grid.mini {
  grid-template-columns: repeat(3, 1fr);
  margin-top: 0.55rem;
}
.ide-guide {
  margin-top: 0.65rem;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-soft);
  background: var(--surface-soft);
}
.ide-guide summary {
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 600;
}
.ide-guide ol {
  margin: 0.5rem 0 0;
  padding-left: 1.25rem;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
}
.verify-lifecycle-card details {
  margin-top: 0.55rem;
  font-size: 0.78rem;
}
.verify-lifecycle-card summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--text);
}
.verify-lifecycle-card ol {
  margin: 0.45rem 0 0;
  padding-left: 1.25rem;
  line-height: 1.45;
  color: var(--muted);
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.55rem;
  margin-top: 0.75rem;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
  padding: 0.75rem 0.4rem;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  color: inherit;
  font: inherit;
}
.stat-cell.clickable {
  cursor: pointer;
}
.stat-cell.clickable:hover {
  border-color: var(--accent);
}
.stat-n {
  font-size: 1.35rem;
  font-weight: 700;
}
.stat-l {
  font-size: 0.72rem;
  color: var(--muted);
}
.action-list,
.activity-list {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.action-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  font-size: 0.85rem;
}
.action-count {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.linkish {
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  font-size: inherit;
  padding: 0 0 0 0.35rem;
}
.linkish:hover {
  text-decoration: underline;
}
.linkish.inline {
  font-size: 0.85rem;
}
@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .dash-grid {
    grid-template-columns: 1fr;
  }
}
</style>
