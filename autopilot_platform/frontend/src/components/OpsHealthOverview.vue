<script setup lang="ts">
/**
 * Ops 配置健康概览（AUD-2026-12 Wave 5）。
 */
import type { OpsHealthNavAction, OpsHealthRow } from "../utils/opsHealthRows";

defineProps<{
  rows: OpsHealthRow[];
  ops: {
    runners_online: number;
    runners_offline?: number;
    runners_total: number;
    devices_busy: number;
    devices_total: number;
    ai?: {
      tokens?: {
        total_tokens?: number | string;
        daily_budget?: number | string;
        budget_remaining?: number | string;
      };
      degraded?: {
        degraded_cases?: number;
        logical_cases?: number;
        ratio?: number;
      };
    };
  } | null;
}>();

const emit = defineEmits<{
  selectNav: [id: OpsHealthNavAction];
  goCluster: [];
}>();
</script>

<template>
  <section class="cc-overview" aria-labelledby="ops-health-heading">
    <h3 id="ops-health-heading">配置健康</h3>

    <ul class="cc-health-list">
      <li v-for="row in rows" :key="row.id" class="cc-health-row">
        <div class="cc-health-main">
          <span class="cc-health-label">{{ row.label }}</span>
          <span
            class="cc-health-value"
            :class="{ mono: row.id === 'model' || row.id === 'rag', warning: row.emphasize }"
          >{{ row.value }}</span>
          <span v-if="row.detail" class="cc-health-detail mono">{{ row.detail }}</span>
        </div>
        <button
          type="button"
          class="small linkish"
          :aria-label="row.label + '：' + row.actionLabel"
          @click="emit('selectNav', row.action)"
        >
          {{ row.actionLabel }}
        </button>
      </li>
    </ul>

    <section class="cc-cluster" aria-labelledby="ops-cluster-heading">
      <div class="cc-cluster-head">
        <h4 id="ops-cluster-heading">集群状态</h4>
        <button type="button" class="small linkish" @click="emit('goCluster')">查看集群</button>
      </div>
      <dl v-if="ops" class="cc-cluster-stats">
        <div>
          <dt>执行节点</dt>
          <dd>{{ ops.runners_online }} 在线 · {{ ops.runners_offline ?? Math.max(0, ops.runners_total - ops.runners_online) }} 离线</dd>
        </div>
        <div>
          <dt>设备</dt>
          <dd>{{ ops.devices_busy }} 占用 / {{ ops.devices_total }} 在线</dd>
        </div>
        <div v-if="ops.ai">
          <dt>今日 Token</dt>
          <dd>
            {{ ops.ai.tokens?.total_tokens ?? "—" }}
            <template v-if="ops.ai.tokens?.daily_budget">
              / {{ ops.ai.tokens.daily_budget }}（剩余 {{ ops.ai.tokens.budget_remaining ?? "—" }}）
            </template>
          </dd>
        </div>
        <div v-if="ops.ai">
          <dt>降级用例</dt>
          <dd>
            {{ ops.ai.degraded?.degraded_cases ?? 0 }}
            <template v-if="ops.ai.degraded?.logical_cases">
              / {{ ops.ai.degraded.logical_cases }}（{{ Math.round(Number(ops.ai.degraded.ratio || 0) * 100) }}%）
            </template>
          </dd>
        </div>
      </dl>
      <p v-else class="cc-cluster-empty">集群状态暂不可用</p>
    </section>
  </section>
</template>

<style scoped>
.cc-overview {
  min-width: 0;
}

.cc-overview h3,
.cc-cluster h4 {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: 650;
}

.cc-overview h3 {
  font-size: 1.05rem;
  margin-bottom: 0.65rem;
}

.cc-health-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--line-soft);
}

.cc-health-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 0.4rem 1rem;
  padding: 0.65rem 0;
  border-bottom: 1px solid var(--line-soft);
}

.cc-health-main {
  display: grid;
  grid-template-columns: minmax(5.5rem, 9rem) minmax(0, 1fr);
  align-items: baseline;
  gap: 0.25rem 0.75rem;
  min-width: 0;
}

.cc-health-label {
  font-weight: 600;
}

.cc-health-value,
.cc-health-detail {
  overflow-wrap: anywhere;
}

.cc-health-value {
  color: var(--muted);
}

.cc-health-value.warning,
.cc-health-detail {
  color: var(--warning-soft-fg);
}

.cc-health-detail {
  grid-column: 2;
  font-size: var(--font-size-meta);
}

.cc-cluster {
  padding-top: 1rem;
}

.cc-cluster-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.cc-cluster-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(12rem, 100%), 1fr));
  gap: 0.65rem 1rem;
  margin: 0.5rem 0 0;
  font-variant-numeric: tabular-nums;
}

.cc-cluster-stats dt {
  color: var(--muted);
  font-size: var(--font-size-meta);
}

.cc-cluster-stats dd,
.cc-cluster-empty {
  margin: 0.15rem 0 0;
  overflow-wrap: anywhere;
}

.cc-cluster-empty {
  color: var(--muted);
}

@media (max-width: 650px) {
  .cc-health-main {
    grid-template-columns: minmax(0, 1fr);
  }

  .cc-health-detail {
    grid-column: 1;
  }
}
</style>
