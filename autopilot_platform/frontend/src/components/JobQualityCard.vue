<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../api";
import { fetchJobQuality, type JobQualitySnapshot } from "../api/jobQuality";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";

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
const snap = ref<JobQualitySnapshot | null>(null);

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
    snap.value = await fetchJobQuality(props.projectId || undefined);
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e);
    snap.value = null;
  } finally {
    loading.value = false;
  }
}

const pct = (r: number) => `${Math.round(Number(r || 0) * 100)}%`;

const CLASS_LABEL: Record<string, string> = {
  assertion: "断言",
  timeout: "超时",
  environment: "环境",
  locator: "定位",
  other: "其他",
};

const ATTR_LABEL: Record<string, string> = {
  product_bug: "产品缺陷",
  env_issue: "环境问题",
  inner_agent_bug: "Agent/定位",
  tooling_gap: "工具链",
  uncertain: "证据不足",
};

const topFails = computed(() => {
  const fr = snap.value?.fail_reason_top || {};
  return Object.entries(fr)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
});

const topClasses = computed(() => {
  const fc = snap.value?.fail_class_top || {};
  return Object.entries(fc)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([k, n]) => [CLASS_LABEL[k] || k, n] as [string, number]);
});

const topAttributions = computed(() => {
  const at = snap.value?.attribution_top || {};
  return Object.entries(at)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([k, n]) => [ATTR_LABEL[k] || k, n] as [string, number]);
});

const topErrors = computed(() => {
  const er = snap.value?.error_prefix_top || {};
  return Object.entries(er)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
});

/** 近 7 天迷你条：失败占比高度 */
const spark = computed(() => {
  const days = (snap.value?.trend || []).slice(-7);
  return days.map((d) => ({
    day: d.day.slice(5),
    h: d.total ? Math.max(8, Math.round(d.fail_rate * 100)) : 4,
    failed: d.failed,
    total: d.total,
    title: `${d.day}: ${d.failed}/${d.total} 失败`,
  }));
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
  <div class="job-quality panel">
    <div class="panel-head-row">
      <h3>批跑失败趋势</h3>
      <div class="head-actions">
        <button type="button" class="small" :disabled="loading" @click="load">刷新</button>
        <button type="button" class="small" @click="emit('goto-tab', 'reports')">报告</button>
      </div>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div v-else-if="loading && !snap" class="empty-state compact"><span>加载中…</span></div>
    <template v-else-if="snap">
      <div class="stat-grid">
        <div class="stat-cell">
          <span class="stat-n">{{ snap.jobs_scanned }}</span>
          <span class="stat-l">{{ snap.days }} 日 Job</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ pct(snap.fail_rate) }}</span>
          <span class="stat-l">终态失败率</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ snap.failed_jobs }}</span>
          <span class="stat-l">失败任务</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ snap.failed_steps }}</span>
          <span class="stat-l">失败步（扫报告）</span>
        </div>
      </div>

      <div v-if="spark.length" class="spark" aria-label="近 7 日失败占比">
        <div
          v-for="b in spark"
          :key="b.day"
          class="spark-bar"
          :style="{ height: b.h + '%' }"
          :title="b.title"
        >
          <span class="spark-d">{{ b.day }}</span>
        </div>
      </div>

      <div v-if="topClasses.length" class="status-block">
        <div class="status-title">失败分类</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topClasses" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topAttributions.length" class="status-block">
        <div class="status-title">失败归因（谁背锅）</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topAttributions" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topFails.length" class="status-block">
        <div class="status-title">fail_reason Top（全步）</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topFails" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topErrors.length" class="status-block">
        <div class="status-title">Job.error 前缀 Top</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topErrors" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <p v-if="!snap.jobs_scanned" class="empty-hint">所选范围内暂无批跑记录</p>
      <p v-else class="meta-line">
        扫 {{ snap.reports_scanned }} 份 result · {{ snap.note }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.job-quality {
  margin: 0;
}
.panel-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
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
  margin-bottom: 0.75rem;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
}
.stat-n {
  font-size: 1.15rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.stat-l {
  font-size: 0.72rem;
  opacity: 0.72;
}
.spark {
  display: flex;
  align-items: flex-end;
  gap: 0.35rem;
  height: 56px;
  margin: 0 0 0.85rem;
  padding: 0 0.15rem;
}
.spark-bar {
  flex: 1;
  min-width: 0;
  background: var(--danger-soft-bg, #fde8e8);
  border: 1px solid var(--danger-soft-border, #f5c2c2);
  border-radius: 4px 4px 0 0;
  position: relative;
}
.spark-d {
  position: absolute;
  left: 50%;
  bottom: -1.1rem;
  transform: translateX(-50%);
  font-size: 0.62rem;
  opacity: 0.65;
  white-space: nowrap;
}
.status-block {
  margin-bottom: 0.65rem;
}
.status-title {
  font-size: 0.78rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
  opacity: 0.8;
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
  align-items: baseline;
  padding: 0.2rem 0.45rem;
  border-radius: 6px;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  font-size: 0.75rem;
  max-width: 100%;
}
.chip-k {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 14rem;
}
.chip-n {
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  opacity: 0.8;
}
.meta-line,
.empty-hint,
.err {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
  opacity: 0.75;
}
.err {
  color: var(--danger-soft-fg, #b42318);
  opacity: 1;
}
@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
