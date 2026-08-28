<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../../api";
import { fetchDesignStats, type DesignDomainStats } from "../../api/designStats";
import { formatAutomationStatusKey, formatReviewStatusKey } from "../../utils/designStatusLabels";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../../stores/auth";

const props = defineProps<{
  projectId?: string;
}>();

const emit = defineEmits<{
  (e: "goto-tab", tab: string): void;
}>();

const auth = useAuthStore();
const { loggedIn } = storeToRefs(auth);
const loading = ref(false);
const error = ref("");
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
    stats.value = await fetchDesignStats(props.projectId || undefined);
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
    stats.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => props.projectId, load);
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

defineExpose({ reload: load });
</script>

<template>
  <div class="design-stats panel">
    <div class="panel-head-row">
      <h3>设计域</h3>
      <div class="head-actions">
        <button type="button" class="small" :disabled="loading" @click="load">刷新</button>
        <button type="button" class="small primary" @click="emit('goto-tab', 'design-dashboard')">打开</button>
      </div>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="loading && !stats" class="empty-state compact"><span>加载中…</span></div>
    <template v-else-if="stats">
      <div class="stat-grid">
        <button type="button" class="stat-cell clickable" @click="emit('goto-tab', 'design-docs')">
          <span class="stat-n">{{ stats.requirements }}</span>
          <span class="stat-l">需求</span>
        </button>
        <button type="button" class="stat-cell clickable" @click="emit('goto-tab', 'design-cases')">
          <span class="stat-n">{{ stats.logical_cases }}</span>
          <span class="stat-l">意图用例</span>
        </button>
        <button type="button" class="stat-cell clickable" @click="emit('goto-tab', 'design-knowledge')">
          <span class="stat-n">{{ stats.knowledge }}</span>
          <span class="stat-l">知识条目</span>
        </button>
        <button type="button" class="stat-cell clickable" @click="emit('goto-tab', 'design-docs')">
          <span class="stat-n">{{ stats.documents }}</span>
          <span class="stat-l">文档</span>
        </button>
      </div>

      <div v-if="Object.keys(stats.by_automation_status).length" class="status-block">
        <div class="status-title">自动化状态</div>
        <ul class="status-chips">
          <li v-for="(n, k) in stats.by_automation_status" :key="k">
            <span class="chip-k">{{ formatAutomationStatusKey(String(k)) }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="Object.keys(stats.by_review_status).length" class="status-block">
        <div class="status-title">评审状态</div>
        <ul class="status-chips">
          <li v-for="(n, k) in stats.by_review_status" :key="k">
            <span class="chip-k">{{ formatReviewStatusKey(String(k)) }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div
        v-if="stats.ai_degraded && (stats.ai_degraded.degraded_cases || 0) > 0"
        class="status-block warn"
      >
        <div class="status-title">AI 降级用例</div>
        <p class="degraded-line">
          {{ stats.ai_degraded.degraded_cases }} / {{ stats.ai_degraded.logical_cases || stats.logical_cases }}
          （{{ Math.round(Number(stats.ai_degraded.ratio || 0) * 100) }}%）需人工重点审阅
        </p>
      </div>
    </template>
    <div v-else class="empty-state compact"><span>暂无设计域数据</span></div>
  </div>
</template>

<style scoped>
.design-stats {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.panel-head-row h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}

.head-actions {
  display: flex;
  gap: 0.4rem;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.55rem;
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
  color: var(--text);
}

.stat-l {
  font-size: 0.72rem;
  color: var(--muted);
}

.status-block {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.status-block.warn .status-title {
  color: var(--bad, #b45309);
}

.degraded-line {
  margin: 0;
  font-size: 0.82rem;
  color: var(--bad, #b45309);
}

.status-title {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.status-chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.status-chips li {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.55rem;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  font-size: 0.78rem;
}

.chip-k {
  color: var(--muted);
}

.chip-n {
  font-weight: 700;
}

.err {
  color: var(--bad);
  font-size: 0.85rem;
}

.empty-state.compact {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 72px;
  padding: 1rem;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--muted);
  font-size: 0.85rem;
}

@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
