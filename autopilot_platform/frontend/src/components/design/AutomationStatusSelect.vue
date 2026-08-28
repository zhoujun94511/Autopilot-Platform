<script setup lang="ts">
import { computed } from "vue";
import {
  AUTOMATION_STATUS_OPTIONS,
  type AutomationStatus,
} from "../../api/designCases";
import { automationStatusHint } from "./automationStatusHints";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  modelValue: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: AutomationStatus | string];
  change: [value: AutomationStatus | string];
}>();

const selectTitle = computed(() => automationStatusHint(props.modelValue));
const options = computed(() =>
  AUTOMATION_STATUS_OPTIONS.map((opt) => ({
    value: opt.value,
    label: opt.label,
    title: automationStatusHint(opt.value),
  })),
);

function onChange(v: string) {
  emit("update:modelValue", v);
  emit("change", v);
}
</script>

<template>
  <ApSelect
    class="automation-status-select"
    size="compact"
    :model-value="props.modelValue"
    :options="options"
    :disabled="props.disabled"
    :title="selectTitle"
    @update:model-value="onChange"
  />
</template>

<style scoped>
.automation-status-select {
  min-width: 8rem;
  max-width: 12rem;
}
</style>
