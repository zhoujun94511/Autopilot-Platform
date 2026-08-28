<script setup lang="ts">
import { computed } from "vue";
import { statusLabel, normalizeStatus } from "../utils/status";

const props = withDefaults(
  defineProps<{
    status: string;
    /** 覆盖展示文案；默认中文映射 */
    label?: string;
  }>(),
  { label: undefined },
);

const cls = computed(() => `status-${normalizeStatus(props.status)}`);
const text = computed(() => props.label ?? statusLabel(props.status));
</script>

<template>
  <span class="status-badge status-pill" :class="cls">{{ text }}</span>
</template>
