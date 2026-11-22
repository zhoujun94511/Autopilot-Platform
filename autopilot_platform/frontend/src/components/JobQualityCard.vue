<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ensureFreshSession } from "../api";
import { fetchJobQuality, type JobQualitySnapshot } from "../api/jobQuality";
import { storeToRefs } from "pinia";
import { useAuthStore } from "../stores/auth";
import { useProjectsStore } from "../stores/projectsStore";

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
const snap = ref<JobQualitySnapshot | null>(null);
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
    const result = await fetchJobQuality(projectId);
    if (generation === loadGeneration) snap.value = result;
  } catch (e: unknown) {
    if (generation === loadGeneration) error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

const pct = (r: number) => `${Math.round(Number(r || 0) * 100)}%`;
const failRateLabel = computed(() =>
  snap.value && snap.value.terminal_jobs > 0 ? pct(snap.value.fail_rate) : "无样本",
);

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

const spark = computed(() => {
  const days = (snap.value?.trend || []).slice(-7);
  if (!days.some((day) => day.total > 0)) return [];
  return days.map((d) => ({
    day: d.day.slice(5),
    height: Math.round(d.fail_rate * 100),
    title: `${d.day}: ${d.failed}/${d.total} 失败`,
  }));
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
  <div class="job-quality panel">
    <div class="panel-head-row">
      <h3>批跑失败趋势</h3>
      <div class="head-actions">
        <button type="button" class="small" :disabled="loading" @click="load">刷新</button>
        <button type="button" class="small" @click="emit('goto-tab', 'reports')">报告</button>
      </div>
    </div>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <p v-else-if="loading && !snap" class="empty-hint" role="status">正在读取批跑统计…</p>
    <p v-else-if="snap && !snap.jobs_scanned" class="empty-hint">近 {{ snap.days }} 天暂无批跑记录</p>
    <template v-else-if="snap">
      <div class="stat-grid">
        <div class="stat-cell">
          <span class="stat-n">{{ snap.jobs_scanned }}</span>
          <span class="stat-l">近 {{ snap.days }} 天批跑</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n" :title="failRateLabel === '无样本' ? '范围内没有终态批跑，不能当成 0% 失败' : ''">{{ failRateLabel }}</span>
          <span class="stat-l">终态失败率</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ snap.failed_jobs }}</span>
          <span class="stat-l">失败任务</span>
        </div>
        <div class="stat-cell">
          <span class="stat-n">{{ snap.failed_steps }}</span>
          <span class="stat-l">失败步骤</span>
        </div>
      </div>

      <div v-if="spark.length" class="spark" role="list" aria-label="近 7 日失败占比">
        <div
          v-for="b in spark"
          :key="b.day"
          class="spark-day"
          role="listitem"
          :aria-label="b.title"
          :title="b.title"
        >
          <span class="spark-track" aria-hidden="true">
            <span class="spark-bar" :style="{ height: b.height + '%' }"></span>
          </span>
          <span class="spark-date" aria-hidden="true">{{ b.day }}</span>
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
        <div class="status-title">失败归因</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topAttributions" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topFails.length" class="status-block">
        <div class="status-title">常见失败原因</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topFails" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topErrors.length" class="status-block">
        <div class="status-title">常见任务错误</div>
        <ul class="status-chips">
          <li v-for="([k, n]) in topErrors" :key="k">
            <span class="chip-k">{{ k }}</span>
            <span class="chip-n">{{ n }}</span>
          </li>
        </ul>
      </div>

      <p class="meta-line">扫描 {{ snap.reports_scanned }} 份报告</p>
      <details v-if="snap.note" class="meta-line">
        <summary>统计口径</summary>
        {{ snap.note }}
      </details>
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
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
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
  margin-bottom: 0.75rem;
  background: var(--line-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.45rem 0.65rem;
  border-radius: 0;
  background: var(--panel);
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
.spark {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 0.25rem;
  margin: 0 0 0.85rem;
}
.spark-day {
  display: grid;
  justify-items: center;
  gap: 0.2rem;
  min-width: 0;
}
.spark-track {
  display: flex;
  align-items: end;
  width: 100%;
  height: 42px;
  border-bottom: 1px solid var(--line);
}
.spark-bar {
  width: 100%;
  background: var(--danger-soft-border);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}
.spark-date {
  color: var(--muted);
  font-size: 0.625rem;
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
  border-radius: var(--radius-md);
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
  color: var(--muted);
  font-size: var(--font-size-meta);
}
.err {
  color: var(--danger-soft-fg);
}
</style>
