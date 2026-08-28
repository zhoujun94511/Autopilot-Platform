<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../api";
import { fetchAgentOps, type AgentOpsSnapshot } from "../api/agentOps";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useCapabilities } from "../composables/useCapabilities";

const props = defineProps<{
  projectId?: string;
}>();

const emit = defineEmits<{
  (e: "goto-tab", tab: string): void;
}>();

const auth = useAuthStore();
const { loggedIn } = storeToRefs(auth);
const caps = useCapabilities();
const loading = ref(false);
const error = ref("");
const snap = ref<AgentOpsSnapshot | null>(null);

async function load() {
  if (!loggedIn.value) {
    snap.value = null;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const ready = await ensureFreshSession();
    if (!ready || !loggedIn.value) {
      snap.value = null;
      return;
    }
    snap.value = await fetchAgentOps(props.projectId || undefined);
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
    snap.value = null;
  } finally {
    loading.value = false;
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
watch(() => props.projectId, load);
watch(
  () => loggedIn.value,
  (ok) => {
    if (ok) void load();
    else {
      snap.value = null;
      error.value = "";
    }
  },
);

defineExpose({ reload: load });
</script>

<template>
  <div class="agentops panel">
    <div class="panel-head-row">
      <h3>{{ caps.canOps ? "AgentOps" : "执行质量" }}</h3>
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

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="loading && !snap" class="empty-state compact"><span>加载中…</span></div>
    <template v-else-if="snap">
      <div class="stat-grid">
        <div class="stat-cell">
          <span class="stat-n">{{ snap.trace.intent_steps }}</span>
          <span class="stat-l">Intent 步</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.cache_hit_rate) }}</span>
          <span class="stat-l">Cache 命中</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.heal_rate) }}</span>
          <span class="stat-l">Heal 率</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.trace.vision_rate) }}</span>
          <span class="stat-l">Vision 率</span>
        </div>
      </div>

      <p class="meta-line">
        扫 {{ snap.trace.reports_scanned }} 份 result · 步均
        {{ snap.trace.avg_latency_ms }} ms · Vision tokens
        {{ snap.trace.vision_tokens_sum }}
        <template v-if="snap.trace.evidence_steps">
          · 证据步 {{ snap.trace.evidence_steps }}
        </template>
      </p>

      <div v-if="topFails.length" class="status-block">
        <div class="status-title">fail_reason Top</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topFails" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <p v-if="caps.canViewOpsBudget && snap.tokens && !snap.tokens.error" class="meta-line">
        AI 今日 token {{ snap.tokens.total_tokens ?? "—" }}
        <template v-if="snap.tokens.daily_budget">
          / 预算 {{ snap.tokens.daily_budget }}
        </template>
        · 调用 {{ snap.tokens.calls ?? "—" }}
      </p>
      <p v-else-if="!snap.trace.intent_steps" class="empty-hint">
        暂无 Intent Trace；批跑上传 result.json 后出现
      </p>
    </template>
  </div>
</template>

<style scoped>
.agentops {
  margin-top: 0.75rem;
}
.panel-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.panel-head-row h3 {
  margin: 0;
  font-size: 1rem;
}
.head-actions {
  display: flex;
  gap: 0.35rem;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.5rem;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 0.5rem 0.6rem;
  border-radius: 6px;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  color: inherit;
}
.stat-n {
  font-size: 1.15rem;
  font-weight: 600;
}
.stat-l {
  font-size: 0.75rem;
  opacity: 0.7;
}
.meta-line {
  margin: 0.55rem 0 0;
  font-size: 0.8rem;
  opacity: 0.8;
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
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  background: var(--surface-soft);
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
  margin: 0.5rem 0 0;
  font-size: 0.8rem;
  opacity: 0.65;
}
@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
