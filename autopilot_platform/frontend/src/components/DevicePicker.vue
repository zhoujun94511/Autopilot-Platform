<script setup lang="ts">
/**
 * 执行路径设备选择（批跑 / 计划共用）。
 *
 * 借鉴：
 * - AWS Device Farm / Jenkins：可选具体设备，或留空走池/自动分配
 * - DeviceFarmer / OpenSTF：多选列表 + 搜索 + 平台徽标，而非运维整页
 *
 * 不包含：设备池 CRUD、占用释放、维护——那些仍在「设备与执行」。
 */
import { computed, ref, watch } from "vue";
import type { Device } from "../api";
import {
  deviceSearchHaystack,
  filterDevicesForPick,
  parseUdids,
  serializeUdids,
} from "../composables/devicePick";
import { displayName, platformBadgeLabel } from "../utils/deviceDisplay";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    devices?: readonly Device[];
    platform?: string;
    backendMode?: string;
    disabled?: boolean;
    /** 紧凑模式：计划弹窗 */
    compact?: boolean;
    inputId?: string;
  }>(),
  {
    modelValue: "",
    devices: () => [],
    platform: "",
    backendMode: "auto",
    disabled: false,
    compact: false,
    inputId: "device-udids",
  },
);

const emit = defineEmits<{ "update:modelValue": [string] }>();

const query = ref("");
const showManual = ref(false);
const searchEl = ref<HTMLInputElement | null>(null);

const selected = computed(() => new Set(parseUdids(props.modelValue)));

const candidates = computed(() =>
  filterDevicesForPick(props.devices, {
    platform: props.platform,
    backendMode: props.backendMode,
  }),
);

const visible = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return candidates.value;
  return candidates.value.filter((d) => deviceSearchHaystack(d).includes(q));
});

const pickMode = computed(() => (selected.value.size > 0 ? "pick" : "auto"));
const listMaxHeight = computed(() => (props.compact ? "160px" : "220px"));

function setModel(next: Set<string> | string[]) {
  emit("update:modelValue", serializeUdids(next));
}

function setAuto() {
  setModel([]);
  query.value = "";
}

function focusPick() {
  showManual.value = false;
  searchEl.value?.focus();
}

function toggle(udid: string) {
  if (props.disabled) return;
  const next = new Set(selected.value);
  if (next.has(udid)) next.delete(udid);
  else next.add(udid);
  setModel(next);
}

function onManualInput(ev: Event) {
  const v = (ev.target as HTMLInputElement).value;
  emit("update:modelValue", v);
}

// 平台 / backend 变化时剔除不再匹配的勾选（保留手填未知 UDID）
watch(
  () => [props.platform, props.backendMode, props.devices] as const,
  () => {
    if (!selected.value.size) return;
    const allowed = new Set(candidates.value.map((d) => d.udid));
    const kept = [...selected.value].filter((u) => {
      // 列表里没有的视为手填，保留
      const inInventory = (props.devices || []).some((d) => d.udid === u);
      return !inInventory || allowed.has(u);
    });
    if (kept.length !== selected.value.size) setModel(kept);
  },
);

</script>

<template>
  <div class="device-picker" :class="{ compact, disabled }">
    <div class="dp-head">
      <div class="dp-title-row">
        <h3 v-if="!compact" class="dp-title">
          选设备
          <span class="title-optional">可选 · 留空由任意空闲节点领取</span>
        </h3>
        <label v-else class="dp-compact-label">目标设备</label>
        <span v-if="selected.size" class="count-chip">已选 {{ selected.size }}</span>
      </div>
      <div class="dp-mode" role="group" aria-label="设备选择方式">
        <button
          type="button"
          class="dp-mode-btn"
          :class="{ active: pickMode === 'auto' }"
          :disabled="disabled"
          @click="setAuto"
        >
          自动分配
        </button>
        <button
          type="button"
          class="dp-mode-btn"
          :class="{ active: pickMode === 'pick' }"
          :disabled="disabled"
          @click="focusPick"
        >
          指定设备
        </button>
      </div>
    </div>

    <p class="dp-hint">
      <template v-if="pickMode === 'auto'">
        不指定设备时，系统会自动挑选空闲设备。
      </template>
      <template v-else>
        已选 {{ selected.size }} 台。占用中的设备无法勾选，也可在下方手动填写。
      </template>
    </p>

    <div class="dp-toolbar">
      <input
        ref="searchEl"
        v-model="query"
        type="search"
        class="dp-search"
        placeholder="搜索名称 / 设备编号 / 节点…"
        :disabled="disabled"
        aria-label="筛选设备"
      />
      <button
        v-if="selected.size"
        type="button"
        class="linkish"
        :disabled="disabled"
        @click="setAuto"
      >
        清空选择
      </button>
    </div>

    <div v-if="visible.length" class="device-pick-list">
      <label
        v-for="d in visible"
        :key="d.udid + d.runner_id"
        class="device-pick-row"
        :class="{ busy: d.busy, checked: selected.has(d.udid) }"
      >
        <input
          type="checkbox"
          :checked="selected.has(d.udid)"
          :disabled="disabled || Boolean(d.busy)"
          @change="toggle(d.udid)"
        />
        <span class="platform-mini-badge" :class="(d.platform || '').toLowerCase()">
          {{ platformBadgeLabel(d.platform) }}
        </span>
        <span class="device-main">
          <span class="device-label">{{ displayName(d) }}</span>
          <span class="device-meta">
            <span v-if="d.os_version" class="os-hint">{{ d.os_version }}</span>
            <span class="mono udid-hint">{{ d.udid }}</span>
            <span v-if="d.backends?.length" class="backend-tags">{{ d.backends.join(", ") }}</span>
            <span class="runner-hint">{{ d.runner_id }}</span>
          </span>
        </span>
        <span v-if="d.busy" class="busy-tag">占用中</span>
        <span v-else-if="d.state && d.state !== 'ready'" class="busy-tag">{{ d.state }}</span>
      </label>
    </div>
    <p v-else class="dp-empty">
      当前没有匹配的在线设备。请确认执行程序已启动、手机已授权；也可以在下方手动填写。
    </p>

    <details class="dp-manual" :open="showManual || undefined">
      <summary>手填设备编号（高级）</summary>
      <div class="dp-manual-body">
        <label class="sr-only" :for="inputId">设备编号</label>
        <input
          :id="inputId"
          :value="modelValue"
          :disabled="disabled"
          placeholder="例如 emulator-5554（多台用逗号分隔）"
          @input="onManualInput"
        />
        <p class="dp-hint">勾选上表会同步到这里；也可以直接粘贴设备编号。</p>
      </div>
    </details>
  </div>
</template>

<style scoped>
.device-picker {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.device-picker.disabled {
  opacity: 0.72;
  pointer-events: none;
}

.dp-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.55rem;
}

.dp-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.dp-title {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text);
}

.title-optional {
  margin-left: 0.35rem;
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--muted);
}

.dp-compact-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

.count-chip {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: var(--action-selected, var(--indigo-soft-bg));
  color: var(--accent-text, var(--text));
  border: 1px solid var(--border-weak, var(--line));
}

.dp-mode {
  display: inline-flex;
  padding: 0.15rem;
  gap: 0.15rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-md, 6px);
  background: var(--surface-soft, var(--control-bg));
}

.dp-mode-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.75rem;
  font-weight: 650;
  padding: 0.28rem 0.65rem;
  border-radius: var(--radius-sm, 4px);
  cursor: pointer;
}

.dp-mode-btn.active {
  background: var(--nav-active-bg, var(--action-selected));
  color: var(--nav-active-fg, var(--text));
}

.dp-mode-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.dp-hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--muted);
  line-height: 1.45;
  white-space: normal;
  overflow-wrap: break-word;
}

.dp-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
}

.dp-search {
  flex: 1;
  min-width: 10rem;
}

.dp-empty {
  margin: 0;
  padding: 0.65rem 0.75rem;
  font-size: 0.78rem;
  color: var(--muted);
  border: 1px dashed var(--line);
  border-radius: 6px;
  background: var(--surface-soft, var(--control-bg));
}

.device-pick-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-height: v-bind(listMaxHeight);
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.35rem;
  background: var(--control-bg, var(--surface));
}

.device-pick-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.5rem;
  padding: 0.4rem 0.55rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.82rem;
}

.device-pick-row:hover {
  background: var(--nav-hover);
}

.device-pick-row.checked {
  background: var(--indigo-soft-bg, var(--nav-active-bg));
}

.device-pick-row.busy {
  opacity: 0.55;
  cursor: not-allowed;
}

.device-main {
  flex: 1;
  min-width: 8rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.device-label {
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.device-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.55rem;
}

.udid-hint,
.runner-hint,
.os-hint,
.backend-tags {
  font-size: 0.68rem;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 12rem;
}

.busy-tag {
  font-size: 0.7rem;
  color: var(--bad);
  font-weight: 700;
}

.platform-mini-badge {
  display: inline-block;
  min-width: 2.2em;
  text-align: center;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: var(--control-bg);
  border: 1px solid var(--line);
}

.platform-mini-badge.android {
  color: var(--ok-soft-fg);
}
.platform-mini-badge.ios {
  color: var(--accent-text);
}

.dp-manual {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.45rem 0.65rem;
  background: var(--surface-soft, var(--control-bg));
}

.dp-manual > summary {
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--accent-text, #1565c0);
  user-select: none;
}

.dp-manual-body {
  margin-top: 0.45rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.linkish {
  background: none;
  border: none;
  color: var(--accent-text, #1565c0);
  cursor: pointer;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}
</style>
