<script setup lang="ts">
import { ref, useId, watch } from "vue";
import type { IntentStep, LogicalCase } from "../../api/designCases";
import { automationStatusLabel, reviewStatusLabel } from "../../utils/designStatusLabels";
import ApModal from "../ApModal.vue";
import ApSelect from "../common/ApSelect.vue";

const STEP_ACTIONS = ["open", "click", "type", "assert", "swipe", "wait", "custom"] as const;
const stepActionOptions = STEP_ACTIONS.map((a) => ({ value: a, label: a }));
const priorityOptions = [
  { value: "P0", label: "P0" },
  { value: "P1", label: "P1" },
  { value: "P2", label: "P2" },
  { value: "P3", label: "P3" },
];

const props = defineProps<{
  item: LogicalCase | null;
  readonly?: boolean;
  busy?: boolean;
  saveError?: string;
}>();

const emit = defineEmits<{
  save: [payload: { title: string; priority: string; intent_steps: IntentStep[] }];
  close: [];
}>();

const title = ref("");
const priority = ref("P2");
const steps = ref<IntentStep[]>([]);
const formError = ref("");
const invalidField = ref<"title" | "steps" | "">("");
const id = useId();

function newStepId(): string {
  return `s-${Math.random().toString(36).slice(2, 10)}`;
}

function cloneSteps(raw: IntentStep[] | undefined): IntentStep[] {
  const list = (raw || []).map((s, i) => ({
    id: s.id || `s-${i + 1}`,
    action: s.action || "custom",
    target: s.target || "",
    value: s.value || "",
    platform_hint: s.platform_hint || "any",
    text: s.text || s.target || "",
  }));
  return list.length ? list : [{ id: newStepId(), action: "custom", target: "", value: "", platform_hint: "any", text: "" }];
}

watch(
  () => props.item,
  (it) => {
    formError.value = "";
    invalidField.value = "";
    if (!it) return;
    title.value = it.title || "";
    priority.value = it.priority || "P2";
    steps.value = cloneSteps(it.intent_steps?.length ? it.intent_steps : it.logical_steps?.map((text, index) => ({
      id: `s-${index + 1}`,
      action: "custom",
      text,
    })));
  },
  { immediate: true },
);

function addStep() {
  steps.value = [
    ...steps.value,
    { id: newStepId(), action: "custom", target: "", value: "", platform_hint: "any", text: "" },
  ];
}

function removeStep(index: number) {
  if (steps.value.length <= 1) return;
  steps.value = steps.value.filter((_, i) => i !== index);
}

function submit() {
  if (props.busy || props.readonly) return;
  const trimmedTitle = title.value.trim();
  if (!trimmedTitle) {
    formError.value = "请填写标题";
    invalidField.value = "title";
    return;
  }
  const cleaned = steps.value
    .map((s) => ({
      ...s,
      action: (s.action || "custom").trim() || "custom",
      text: (s.text || "").trim(),
      target: (s.target || "").trim(),
      value: (s.value || "").trim(),
      platform_hint: s.platform_hint || "any",
    }))
    .filter((s) => s.text);
  if (!cleaned.length) {
    formError.value = "请至少保留一步有效意图";
    invalidField.value = "steps";
    return;
  }
  formError.value = "";
  invalidField.value = "";
  emit("save", {
    title: trimmedTitle,
    priority: priority.value || "P2",
    intent_steps: cleaned,
  });
}
</script>

<template>
  <ApModal
    v-if="item"
    :title="readonly ? '查看用例' : '编辑用例'"
    variant="drawer"
    :close-on-backdrop="false"
    :close-on-esc="!busy"
    @close="emit('close')"
  >
    <form :id="id" class="case-form" novalidate @submit.prevent="submit">
      <dl class="case-meta">
        <div><dt>用例编号</dt><dd><code>{{ item.case_key }}</code></dd></div>
        <div><dt>评审</dt><dd>{{ reviewStatusLabel(item.review_status) }}</dd></div>
        <div><dt>自动化状态</dt><dd>{{ automationStatusLabel(item.automation_status) }}</dd></div>
      </dl>

      <div class="field-row">
        <label class="field-label">
          标题
          <input
            v-model="title"
            data-autofocus
            :readonly="readonly"
            :disabled="busy"
            :required="!readonly"
            :aria-invalid="invalidField === 'title'"
            :aria-describedby="invalidField === 'title' ? `${id}-error` : undefined"
            @input="invalidField === 'title' && (invalidField = '')"
          />
        </label>
        <label class="field-label">
          优先级
          <ApSelect
            v-model="priority"
            aria-label="优先级"
            :disabled="readonly || busy"
            :options="priorityOptions"
          />
        </label>
      </div>

      <div class="steps-head">
        <h4>意图步骤</h4>
        <button v-if="!readonly" type="button" class="small" :disabled="busy" @click="addStep">
          添加步骤
        </button>
      </div>
      <ol class="step-editor">
        <li v-for="(step, index) in steps" :key="step.id">
          <span class="step-idx" aria-hidden="true">{{ index + 1 }}</span>
          <ApSelect
            v-model="step.action"
            :aria-label="`步骤 ${index + 1} 的动作`"
            :disabled="readonly || busy"
            :options="stepActionOptions"
          />
          <input
            v-model="step.text"
            :readonly="readonly"
            :disabled="busy"
            :aria-label="`步骤 ${index + 1} 的描述`"
            :aria-invalid="invalidField === 'steps'"
            :aria-describedby="invalidField === 'steps' ? `${id}-error` : undefined"
            placeholder="步骤描述"
            @input="invalidField === 'steps' && (invalidField = '')"
          />
          <button
            v-if="!readonly"
            type="button"
            class="ghost small"
            :disabled="busy || steps.length <= 1"
            :aria-label="`删除步骤 ${index + 1}`"
            @click="removeStep(index)"
          >
            删除
          </button>
        </li>
      </ol>
      <p v-if="invalidField" :id="`${id}-error`" class="form-error" role="alert">{{ formError }}</p>
      <p v-if="saveError" class="form-error" role="alert">{{ saveError }}</p>
    </form>
    <template #actions>
      <button type="button" :disabled="busy" @click="emit('close')">
        {{ readonly ? "关闭" : "取消" }}
      </button>
      <button v-if="!readonly" :form="id" type="submit" class="primary" :disabled="busy">
        {{ busy ? "保存中…" : "保存" }}
      </button>
    </template>
  </ApModal>
</template>

<style scoped>
.case-form {
  min-width: 0;
}
.case-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-4);
  margin: 0 0 var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--line);
}
.case-meta div {
  min-width: 0;
}
.case-meta dt,
.step-idx {
  color: var(--muted);
  font-size: var(--font-size-meta);
}
.case-meta dd {
  margin: var(--space-1) 0 0;
  overflow-wrap: anywhere;
}
.field-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(80px, 120px);
  gap: var(--space-3);
}
.field-label {
  min-width: 0;
}
.steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: var(--space-4) 0 var(--space-2);
}
.steps-head h4 {
  margin: 0;
  font-size: var(--font-size-body);
}
.step-editor {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.step-editor li {
  display: grid;
  grid-template-columns: 16px 96px minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
}
.step-editor input {
  min-width: 0;
}
.step-idx {
  font-variant-numeric: tabular-nums;
}
.form-error {
  margin: var(--space-2) 0 0;
  color: var(--danger-soft-fg);
  font-size: var(--font-size-meta);
}
@media (max-width: 520px) {
  .step-editor li {
    grid-template-columns: 16px minmax(0, 1fr) auto;
  }
  .step-editor input {
    grid-column: 2;
    grid-row: 2;
  }
  .step-editor button:not(.ap-select-trigger) {
    grid-column: 3;
    grid-row: 2;
  }
}
</style>
