<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../api";
import { fetchAgentOps, type AgentOpsSnapshot } from "../api/agentOps";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useProjectsStore } from "../stores/projectsStore";
import { useCapabilities } from "../composables/useCapabilities";

const props = defineProps<{
  projectId?: string;
}>();

const emit = defineEmits<{
  (e: "goto-tab", tab: string): void;
}>();

const auth = useAuthStore();
const { loggedIn } = storeToRefs(auth);
const { filterOrgId } = storeToRefs(useProjectsStore());
const caps = useCapabilities();
const loading = ref(false);
const error = ref("");
const snap = ref<AgentOpsSnapshot | null>(null);
let loadGeneration = 0;

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
    const result = await fetchAgentOps(projectId);
    if (generation === loadGeneration) snap.value = result;
  } catch (e: unknown) {
    if (generation === loadGeneration) error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

const pct = (r: number) => `${Math.round(Number(r || 0) * 100)}%`;

const topFails = computed(() => {
  const fr = snap.value?.trace?.fail_reason || {};
  return Object.entries(fr)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
});

onMounted(load);
watch([filterOrgId, () => props.projectId, loggedIn], () => {
  snap.value = null;
  error.value = "";
  void load();
});

defineExpose({ reload: load });
</script>

<template>
  <div class="agentops panel">
    <div class="panel-head-row">
      <h3>执行质量</h3>
      <div class="head-actions">
        <button type="button" class="small" :disabled="loading" @click="load">刷新</button>
        <button
          v-if="caps.canOps"
          type="button"
          class="small"
          @click="emit('goto-tab', 'ops')"
        >
          运维
        </button>
      </div>
    </div>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <p v-else-if="loading && !snap" class="empty-hint" role="status">正在读取执行统计…</p>
    <template v-else-if="snap">
      <div v-if="snap.trace.intent_steps > 0" class="stat-grid">
        <div class="stat-cell">
          <span class="stat-n">{{ snap.trace.intent_steps }}</span>
          <span class="stat-l">意图步数</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.cache_hit_rate) }}</span>
          <span class="stat-l">缓存命中</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.heal_rate) }}</span>
          <span class="stat-l">自愈比例</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.vision_rate) }}</span>
          <span class="stat-l">看图比例</span>
        </div>
      </div>

      <p v-else class="empty-hint">暂无意图步骤记录</p>

      <p v-if="snap.trace.intent_steps > 0 || snap.trace.reports_scanned > 0" class="meta-line">
        扫描 {{ snap.trace.reports_scanned }} 份结果
        <template v-if="snap.trace.intent_steps > 0">
          · 步均 {{ snap.trace.avg_latency_ms }} 毫秒
          · 看图用量 {{ snap.trace.vision_tokens_sum }}
        </template>
        <template v-if="snap.trace.evidence_steps">
          · 证据步 {{ snap.trace.evidence_steps }}
        </template>
      </p>

      <div v-if="topFails.length" class="status-block">
        <div class="status-title">失败原因</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topFails" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <p
        v-if="caps.canViewOpsBudget && snap.tokens && !snap.tokens.error &&
          (snap.tokens.total_tokens || snap.tokens.calls || snap.tokens.daily_budget)"
        class="meta-line"
      >
        今日模型用量 {{ snap.tokens.total_tokens ?? "—" }}
        <template v-if="snap.tokens.daily_budget">
          / 预算 {{ snap.tokens.daily_budget }}
        </template>
        · 调用 {{ snap.tokens.calls ?? "—" }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.agentops {
  margin: 0;
}
.panel-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.panel-head-row h3 {
  margin: 0;
  font-size: 1rem;
}
.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  background: var(--line-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 0.45rem 0.65rem;
  border-radius: 0;
  background: var(--panel);
  color: inherit;
}
.stat-n {
  font-size: 1.125rem;
  font-weight: 650;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
.stat-l {
  color: var(--muted);
  font-size: var(--font-size-meta);
}
.meta-line {
  margin: 0.55rem 0 0;
  font-size: var(--font-size-meta);
  line-height: 1.45;
  color: var(--muted);
}
.status-block {
  margin-top: 0.65rem;
}
.status-title {
  font-size: 0.75rem;
  font-weight: 600;
  margin-bottom: 0.3rem;
  opacity: 0.75;
}
.status-chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.status-chips li {
  display: inline-flex;
  gap: 0.35rem;
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
  background: transparent;
  border: 1px solid var(--line-soft);
  font-size: 0.75rem;
}
.chip-n {
  font-weight: 600;
}
.err {
  color: var(--danger-soft-fg);
  font-size: 0.85rem;
}
.empty-hint {
  margin: 0.35rem 0 0;
  color: var(--muted);
  font-size: var(--font-size-meta);
}
</style>
