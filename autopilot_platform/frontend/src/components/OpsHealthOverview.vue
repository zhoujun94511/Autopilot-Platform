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
  <div class="cc-overview">
    <div class="cc-panel-head">
      <div>
        <h3 class="cc-panel-title">配置健康</h3>
        <p class="cc-panel-sub">先确认这些项就绪；改参数请从左侧进入对应分类。</p>
      </div>
    </div>

    <div class="cc-health-list">
      <article
        v-for="row in rows"
        :key="row.id"
        class="cc-health-row"
        :class="{ bad: row.emphasize, ok: row.ok && !row.emphasize }"
      >
        <div class="cc-health-main">
          <span class="cc-health-label">{{ row.label }}</span>
          <span class="cc-health-value" :class="{ mono: row.id === 'model' || row.id === 'rag' }">
            {{ row.value }}
          </span>
          <span v-if="row.detail" class="cc-health-detail mono">{{ row.detail }}</span>
        </div>
        <button
          type="button"
          class="small"
          :class="{ primary: row.emphasize }"
          @click="emit('selectNav', row.action)"
        >
          {{ row.actionLabel }}
        </button>
      </article>
    </div>

    <p class="cc-cluster-line">
      <span v-if="ops">
        集群简况：Runner {{ ops.runners_online }} 在线
        <template v-if="(ops.runners_offline ?? Math.max(0, ops.runners_total - ops.runners_online)) > 0">
          · {{ ops.runners_offline ?? ops.runners_total - ops.runners_online }} 已离线
        </template>
        · 设备占用 {{ ops.devices_busy }} / 在线 {{ ops.devices_total }}
      </span>
      <span v-else>集群简况暂不可用</span>
      <button type="button" class="small linkish" @click="emit('goCluster')">查看集群</button>
    </p>
    <p v-if="ops?.ai" class="cc-cluster-line">
      <span>
        AI：今日 token {{ ops.ai.tokens?.total_tokens ?? "—" }}
        <template v-if="ops.ai.tokens?.daily_budget">
          / 预算 {{ ops.ai.tokens.daily_budget }}
          （剩余 {{ ops.ai.tokens.budget_remaining ?? "—" }}）
        </template>
        · 降级用例 {{ ops.ai.degraded?.degraded_cases ?? 0 }}
        <template v-if="ops.ai.degraded?.logical_cases">
          / {{ ops.ai.degraded.logical_cases }}
          （{{ Math.round(Number(ops.ai.degraded.ratio || 0) * 100) }}%）
        </template>
      </span>
    </p>
  </div>
</template>

<style scoped>
.cc-overview {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-width: 0;
}

.cc-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.cc-panel-title {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
}

.cc-panel-sub {
  margin: 0;
  color: var(--muted);
  font-size: 0.84rem;
  line-height: 1.45;
}

.cc-health-list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.cc-health-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.65rem 0.9rem;
  border-radius: 10px;
  border: 1px solid var(--line-soft);
  background: var(--surface-soft);
}

.cc-health-row.bad {
  border-color: var(--warning-soft-border);
  background: var(--warning-soft-bg);
}

.cc-health-main {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
}

.cc-health-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
}

.cc-health-value {
  font-size: 0.92rem;
}

.cc-health-detail {
  font-size: 0.75rem;
  color: var(--bad, #e05a5a);
  word-break: break-all;
}

.cc-cluster-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  font-size: 0.8rem;
  color: var(--muted);
}

.cc-cluster-line .linkish {
  border: none;
  background: transparent;
  color: var(--accent-text, var(--accent));
  text-decoration: underline;
  padding: 0 0.15rem;
  cursor: pointer;
  font: inherit;
}

@media (max-width: 900px) {
  .cc-health-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
