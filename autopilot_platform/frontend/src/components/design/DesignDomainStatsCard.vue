<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { apiErrorMessage, ensureFreshSession } from "../../api";
import { fetchDesignStats, type DesignDomainStats } from "../../api/designStats";
import { formatAutomationStatusKey, formatReviewStatusKey } from "../../utils/designStatusLabels";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../../stores/auth";
import { useProjectsStore } from "../../stores/projectsStore";

const props = defineProps<{
  projectId?: string;
}>();

const emit = defineEmits<{
  (e: "goto-tab", tab: string): void;
}>();

const auth = useAuthStore();
const { loggedIn } = storeToRefs(auth);
const { filterOrgId } = storeToRefs(useProjectsStore());
const loading = ref(false);
const error = ref("");
const stats = ref<DesignDomainStats | null>(null);
let loadGeneration = 0;

const resources = [
  { key: "documents", label: "需求文档", tab: "design-docs" },
  { key: "requirements", label: "需求条目", tab: "design-docs" },
  { key: "logical_cases", label: "意图用例", tab: "design-cases" },
  { key: "knowledge", label: "知识条目", tab: "design-knowledge" },
] as const;

async function load() {
  const generation = ++loadGeneration;
  if (!loggedIn.value) {
    loading.value = false;
    return;
  }
  const projectId = props.projectId || undefined;
  loading.value = true;
  error.value = "";
  try {
    const ready = await ensureFreshSession();
    if (!ready || !loggedIn.value || generation !== loadGeneration) return;
    const result = await fetchDesignStats(projectId);
    if (generation === loadGeneration) stats.value = result;
  } catch (e: unknown) {
    if (generation === loadGeneration) error.value = apiErrorMessage(e);
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

onMounted(load);
watch([filterOrgId, () => props.projectId, loggedIn], () => {
  stats.value = null;
  error.value = "";
  void load();
});

defineExpose({ reload: load });
</script>

<template>
  <section class="design-stats" aria-labelledby="design-stats-title" :aria-busy="loading">
    <header class="design-stats-head">
      <h3 id="design-stats-title">设计资源</h3>
      <div class="head-actions">
        <button type="button" class="small ghost" :disabled="loading" @click="load">刷新</button>
        <button type="button" class="small ghost" @click="emit('goto-tab', 'design-dashboard')">
          设计总览
        </button>
      </div>
    </header>

    <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
    <p v-else-if="loading && !stats" class="stats-empty" role="status">加载中…</p>

    <template v-if="stats">
      <ul class="resource-list">
        <li v-for="resource in resources" :key="resource.key">
          <button type="button" class="resource-link" @click="emit('goto-tab', resource.tab)">
            <span>{{ resource.label }}</span>
            <span class="resource-count">{{ stats[resource.key] }}</span>
          </button>
        </li>
      </ul>

      <details
        v-if="Object.keys(stats.by_automation_status).length || Object.keys(stats.by_review_status).length"
        class="status-summary"
      >
        <summary>用例状态</summary>
        <div class="status-groups">
          <div v-if="Object.keys(stats.by_review_status).length">
            <h4>评审</h4>
            <dl>
              <div v-for="(count, state) in stats.by_review_status" :key="state">
                <dt>{{ formatReviewStatusKey(String(state)) }}</dt>
                <dd>{{ count }}</dd>
              </div>
            </dl>
          </div>
          <div v-if="Object.keys(stats.by_automation_status).length">
            <h4>自动化</h4>
            <dl>
              <div v-for="(count, state) in stats.by_automation_status" :key="state">
                <dt>{{ formatAutomationStatusKey(String(state)) }}</dt>
                <dd>{{ count }}</dd>
              </div>
            </dl>
          </div>
        </div>
      </details>

      <p v-if="(stats.ai_degraded?.degraded_cases ?? 0) > 0" class="degraded-line">
        {{ stats.ai_degraded?.degraded_cases }} 条用例使用了降级生成，请人工复核。
      </p>
    </template>
    <p v-else-if="!loading && !error" class="stats-empty">暂无数据</p>
  </section>
</template>

<style scoped>
.design-stats {
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}

.design-stats-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
}

.design-stats-head h3 {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: 600;
}

.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.resource-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.resource-list li + li {
  border-top: 1px solid var(--line-soft);
}

.resource-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  border: 0;
  border-radius: 0;
  min-height: 40px;
  padding: 8px 16px;
  text-align: start;
  background: transparent;
  box-shadow: none;
  color: var(--accent-text);
}

.resource-link:hover {
  background: var(--action-hover);
  box-shadow: none;
}

.resource-link:focus-visible,
.status-summary > summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.resource-count {
  margin-left: auto;
  color: var(--text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.status-summary {
  border-top: 1px solid var(--line);
  padding: 0 16px;
}

.status-summary > summary {
  width: fit-content;
  min-height: 40px;
  align-content: center;
  cursor: pointer;
  font-weight: 600;
}

.status-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 136px), 1fr));
  gap: 12px 16px;
  padding-bottom: 12px;
}

.status-groups h4 {
  margin: 0 0 4px;
  font-size: var(--font-size-meta);
  color: var(--muted);
  font-weight: 600;
}

.status-groups dl {
  margin: 0;
}

.status-groups dl > div {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  padding-block: 4px;
}

.status-groups dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}

.degraded-line,
.stats-empty {
  margin: 0;
  padding: 12px 16px;
  color: var(--muted);
}

.degraded-line {
  border-top: 1px solid var(--line-soft);
  color: var(--warning-soft-fg);
}
</style>
