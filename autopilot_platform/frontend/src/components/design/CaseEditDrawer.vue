<script setup lang="ts">
import { ref, watch } from "vue";
import type { IntentStep, LogicalCase } from "../../api/designCases";
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
}>();

const emit = defineEmits<{
  save: [payload: { title: string; priority: string; intent_steps: IntentStep[] }];
  close: [];
}>();

const title = ref("");
const priority = ref("P2");
const steps = ref<IntentStep[]>([]);
const formError = ref("");

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
    if (!it) return;
    title.value = it.title || "";
    priority.value = it.priority || "P2";
    steps.value = cloneSteps(it.intent_steps);
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
  const trimmedTitle = title.value.trim();
  if (!trimmedTitle) {
    formError.value = "请填写标题";
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
    return;
  }
  formError.value = "";
  emit("save", {
    title: trimmedTitle,
    priority: priority.value || "P2",
    intent_steps: cleaned,
  });
}
</script>

<template>
  <Teleport to="body">
    <div v-if="item" class="drawer-mask" @click="emit('close')">
      <aside class="drawer" role="dialog" :aria-label="readonly ? '查看用例' : '编辑用例'" @click.stop>
        <header class="drawer-head">
          <div class="drawer-head-main">
            <h3 class="drawer-title">{{ readonly ? "查看用例" : "编辑用例" }}</h3>
            <code class="case-key">{{ item.case_key }}</code>
          </div>
          <button type="button" class="icon-btn" aria-label="关闭" @click="emit('close')">✕</button>
        </header>
        <div class="drawer-body">
          <div class="field-stack">
            <label class="field-label">
              标题
              <input v-model="title" :readonly="readonly" :disabled="busy" placeholder="用例标题" />
            </label>
            <label class="field-label compact">
              优先级
              <ApSelect
                v-model="priority"
                size="compact"
                aria-label="优先级"
                :disabled="readonly || busy"
                :options="priorityOptions"
              />
            </label>
          </div>

          <div class="steps-head">
            <h4>意图步骤</h4>
            <button v-if="!readonly" type="button" class="small" :disabled="busy" @click="addStep">
              加一步
            </button>
          </div>
          <ol class="step-editor">
            <li v-for="(s, i) in steps" :key="s.id">
              <span class="step-idx">{{ i + 1 }}</span>
              <ApSelect
                v-model="s.action"
                size="compact"
                aria-label="动作"
                :disabled="readonly || busy"
                :options="stepActionOptions"
              />
              <input
                v-model="s.text"
                :readonly="readonly"
                :disabled="busy"
                placeholder="步骤描述"
              />
              <button
                v-if="!readonly"
                type="button"
                class="icon-btn"
                :disabled="busy || steps.length <= 1"
                aria-label="删除此步"
                @click="removeStep(i)"
              >
                ✕
              </button>
            </li>
          </ol>
          <p v-if="formError" class="form-err">{{ formError }}</p>
        </div>
        <footer class="drawer-foot">
          <button type="button" :disabled="busy" @click="emit('close')">
            {{ readonly ? "关闭" : "取消" }}
          </button>
          <button
            v-if="!readonly"
            type="button"
            class="primary"
            :disabled="busy"
            @click="submit"
          >
            {{ busy ? "保存中…" : "保存" }}
          </button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(720px, 96vw);
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.1rem;
  border-bottom: 1px solid var(--line);
}
.drawer-head-main {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
}
.drawer-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}
.case-key {
  font-size: 0.72rem;
  color: var(--mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.icon-btn {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.25rem 0.4rem;
  min-height: 0;
  border-radius: 6px;
}
.icon-btn:hover:not(:disabled) {
  background: var(--chip-bg);
  color: var(--text);
}
.drawer-body {
  flex: 1;
  overflow: auto;
  padding: 1rem 1.1rem 1.25rem;
}
.field-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  align-items: flex-end;
}
.field-label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
  min-width: 12rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}
.field-label.compact {
  flex: 0 0 8rem;
  min-width: 8rem;
}
.steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin: 1.1rem 0 0.55rem;
}
.steps-head h4 {
  margin: 0;
  font-size: 0.88rem;
}
.step-editor {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.step-editor li {
  display: grid;
  grid-template-columns: 1.6rem 6.5rem minmax(0, 1fr) 1.8rem;
  gap: 0.4rem;
  align-items: center;
}
.step-idx {
  font-variant-numeric: tabular-nums;
  font-size: 0.75rem;
  color: var(--muted);
  text-align: right;
}
.form-err {
  margin: 0.75rem 0 0;
  color: var(--danger-soft-fg, #b42318);
  font-size: 0.82rem;
}
.drawer-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.85rem 1.1rem;
  border-top: 1px solid var(--line);
}
</style>
