<script setup lang="ts">
/**
 * 占用设备：单表单一次填完（时长 / 用途 / 说明），默认值齐全 → 打开即可确定。
 */
import { computed, ref, watch } from "vue";
import ApModal from "./ApModal.vue";
import {
  RESERVE_DEFAULT_MINUTES,
  RESERVE_DURATION_PRESETS,
  RESERVE_MAX_MINUTES,
  RESERVE_MIN_MINUTES,
  RESERVE_PURPOSES,
  durationLabel,
  reserveDialogState,
  type ReservePurposeId,
} from "../composables/useReserveDialog";
import { udidSummary } from "../utils/deviceDisplay";

const presetMinutes = ref<number | null>(RESERVE_DEFAULT_MINUTES);
const customMinutes = ref("");
const purposeId = ref<ReservePurposeId>("debug");
const note = ref("");

watch(
  () => reserveDialogState.value,
  (s) => {
    if (!s) return;
    presetMinutes.value = RESERVE_DEFAULT_MINUTES;
    customMinutes.value = "";
    purposeId.value = "debug";
    note.value = "";
  },
);

const usingCustom = computed(() => presetMinutes.value === null);

/** 有效分钟数；自定义值非法时为 null，主按钮据此禁用 */
const minutes = computed<number | null>(() => {
  if (!usingCustom.value) return presetMinutes.value;
  const raw = customMinutes.value.trim();
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isInteger(value)) return null;
  if (value < RESERVE_MIN_MINUTES || value > RESERVE_MAX_MINUTES) return null;
  return value;
});

const customError = computed(() => {
  if (!usingCustom.value) return "";
  const raw = customMinutes.value.trim();
  if (!raw) return "";
  return minutes.value === null
    ? `请填 ${RESERVE_MIN_MINUTES}-${RESERVE_MAX_MINUTES} 之间的整数分钟`
    : "";
});

const activePurpose = computed(
  () => RESERVE_PURPOSES.find((p) => p.id === purposeId.value) || RESERVE_PURPOSES[0],
);

const expiresHint = computed(() => {
  const m = minutes.value;
  if (!m) return "";
  const at = new Date(Date.now() + m * 60_000);
  const sameDay = at.toDateString() === new Date().toDateString();
  const time = at.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const label = sameDay
    ? time
    : `${at.getMonth() + 1}月${at.getDate()}日 ${time}`;
  return `到期自动释放：约 ${label}`;
});

const submitLabel = computed(() =>
  minutes.value ? `占用 ${durationLabel(minutes.value)}` : "占用设备",
);

function pickPreset(value: number | null) {
  presetMinutes.value = value;
}

function onCancel() {
  reserveDialogState.value?.resolve(null);
}

function onSubmit() {
  const m = minutes.value;
  if (!m) return;
  const reason = `${activePurpose.value.tag}${note.value.trim()}`.trim();
  reserveDialogState.value?.resolve({ durationMinutes: m, reason });
}
</script>

<template>
  <ApModal
    v-if="reserveDialogState"
    wide
    :title="`占用 ${reserveDialogState.deviceLabel}`"
    :description="`UDID ${udidSummary(reserveDialogState.udid)} · 到期后自动释放，也可随时手动停止占用`"
    @close="onCancel"
  >
    <div class="ap-field">
      <span class="ap-field-label" id="reserve-duration-label">占用时长</span>
      <div class="ap-chip-row" role="group" aria-labelledby="reserve-duration-label">
        <button
          v-for="preset in RESERVE_DURATION_PRESETS"
          :key="preset"
          type="button"
          class="ap-chip"
          :aria-pressed="presetMinutes === preset"
          @click="pickPreset(preset)"
        >
          {{ durationLabel(preset) }}
        </button>
        <button
          type="button"
          class="ap-chip"
          :aria-pressed="usingCustom"
          @click="pickPreset(null)"
        >
          自定义
        </button>
      </div>
      <input
        v-if="usingCustom"
        v-model="customMinutes"
        class="ap-modal-input reserve-custom"
        type="text"
        inputmode="numeric"
        :placeholder="`${RESERVE_MIN_MINUTES}-${RESERVE_MAX_MINUTES} 分钟`"
        aria-label="自定义占用时长（分钟）"
        :aria-invalid="Boolean(customError)"
        @keydown.enter.prevent="onSubmit"
      />
      <p v-if="customError" class="ap-field-error" role="alert">{{ customError }}</p>
      <p v-else-if="expiresHint" class="ap-field-hint">{{ expiresHint }}</p>
    </div>

    <div class="ap-field">
      <span class="ap-field-label" id="reserve-purpose-label">用途</span>
      <div class="ap-chip-row" role="group" aria-labelledby="reserve-purpose-label">
        <button
          v-for="p in RESERVE_PURPOSES"
          :key="p.id"
          type="button"
          class="ap-chip"
          :aria-pressed="purposeId === p.id"
          @click="purposeId = p.id"
        >
          {{ p.label }}
        </button>
      </div>
    </div>

    <div class="ap-field">
      <label class="ap-field-label" for="reserve-note">说明（可选）</label>
      <input
        id="reserve-note"
        v-model="note"
        class="ap-modal-input reserve-note"
        type="text"
        :placeholder="activePurpose.placeholder"
        @keydown.enter.prevent="onSubmit"
      />
      <p class="ap-field-hint">会展示在设备卡上，方便同事知道你在用它做什么。占用成功后可点「远程调试」进入画面控制。</p>
    </div>

    <template #actions>
      <button type="button" class="ap-btn ghost" @click="onCancel">取消</button>
      <button
        type="button"
        class="ap-btn primary"
        :disabled="!minutes"
        data-autofocus
        @click="onSubmit"
      >
        {{ submitLabel }}
      </button>
    </template>
  </ApModal>
</template>

<style scoped>
.reserve-custom,
.reserve-note {
  margin-top: 0.5rem;
  margin-bottom: 0;
}

.reserve-note {
  font-family: inherit;
}
</style>
