<script setup lang="ts">
import { computed, ref } from "vue";
import { useCapabilities } from "../../composables/useCapabilities";
import ApSelect from "../common/ApSelect.vue";

const props = withDefaults(
  defineProps<{
    busy?: boolean;
    bare?: boolean;
  }>(),
  { bare: false },
);

const caps = useCapabilities();
/** 生成用例会落库/去重/审核，必须项目写；闲聊不走本卡片。 */
const canEdit = computed(() => Boolean(caps.canEditProject));

const emit = defineEmits<{
  generate: [payload: { text: string; useRag: boolean; autoApprove: boolean }];
  batchGenerate: [
    payload: {
      requirements: string[];
      caseCountPerReq: number;
      processMode: "sequential" | "parallel";
      useRag: boolean;
      autoApprove: boolean;
    },
  ];
}>();

const mode = ref<"single" | "batch">("single");
const genText = ref("");
const batchText = ref("");
const useRag = ref(true);
const autoApprove = ref(false);
const caseCountPerReq = ref(3);
const processMode = ref<"sequential" | "parallel">("sequential");

function submitSingle() {
  emit("generate", {
    text: genText.value,
    useRag: useRag.value,
    autoApprove: autoApprove.value,
  });
}

function submitBatch() {
  const requirements = batchText.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  emit("batchGenerate", {
    requirements,
    caseCountPerReq: caseCountPerReq.value,
    processMode: processMode.value,
    useRag: useRag.value,
    autoApprove: autoApprove.value,
  });
}

function submit() {
  if (mode.value === "batch") submitBatch();
  else submitSingle();
}

function clear() {
  genText.value = "";
  batchText.value = "";
}

defineExpose({ clear, genText, batchText });
</script>

<template>
  <section :class="bare ? 'gen-card bare' : 'surface-card gen-card'">
    <div class="card-title-row">
      <h3>从需求生成草稿</h3>
      <div class="mode-tabs">
        <button
          type="button"
          class="mode-tab"
          :class="{ active: mode === 'single' }"
          @click="mode = 'single'"
        >
          单条
        </button>
        <button
          type="button"
          class="mode-tab"
          :class="{ active: mode === 'batch' }"
          @click="mode = 'batch'"
        >
          批量
        </button>
      </div>
    </div>

    <div class="field-stack">
      <template v-if="mode === 'single'">
        <label class="field-label">
          需求原文
          <textarea
            v-model="genText"
            rows="5"
            placeholder="粘贴一段需求、验收标准或用户故事…"
          />
        </label>
      </template>
      <template v-else>
        <label class="field-label">
          多条需求（每行一条）
          <textarea
            v-model="batchText"
            rows="6"
            placeholder="每行输入一条需求或用户故事&#10;例如：&#10;用户可以使用手机号登录&#10;登录失败应提示错误原因"
          />
        </label>
        <div class="inline-fields">
          <label class="field-label compact">
            每条生成用例数
            <input v-model.number="caseCountPerReq" type="number" min="1" max="20" />
          </label>
          <label class="field-label compact">
            处理模式
            <ApSelect
              v-model="processMode"
              size="compact"
              aria-label="处理模式"
              :options="[
                { value: 'sequential', label: '顺序' },
                { value: 'parallel', label: '并行' },
              ]"
            />
          </label>
        </div>
        <p v-if="mode === 'batch' && caps.canOps" class="mode-hint">
          说明：选择「并行」且运维开启并行处理时，将为每条需求并发生成；未开启则仍顺序执行。
        </p>
        <p v-else-if="mode === 'batch'" class="mode-hint">
          说明：选择「并行」时由平台按配置决定是否并发生成；未开启则仍顺序执行。
        </p>
      </template>

      <div class="inline-tools">
        <label class="check-line">
          <input v-model="useRag" type="checkbox" :disabled="!canEdit" />
          结合知识库检索（推荐）
        </label>
        <label class="check-line" title="质量较好时先标为「待首次运行」，仍需你跑一遍确认">
          <input v-model="autoApprove" type="checkbox" :disabled="!canEdit" />
          高分半自动批准（待首跑）
        </label>
        <span class="spacer" />
        <button type="button" class="primary" :disabled="props.busy || !canEdit" @click="submit">
          {{ mode === "batch" ? "批量生成意图用例" : "生成意图用例" }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.gen-card.bare {
  padding: 0.35rem 0 0;
  border: none;
  background: transparent;
}
textarea {
  resize: vertical;
  min-height: 7rem;
}
.check-line {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.85rem;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}
.check-line input {
  width: auto;
  margin: 0;
}
.mode-tabs {
  display: inline-flex;
  gap: 0.25rem;
  background: var(--chip-bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.15rem;
}
.mode-tab {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 0.78rem;
  padding: 0.25rem 0.65rem;
  border-radius: 6px;
  cursor: pointer;
}
.mode-tab.active {
  background: var(--panel);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.inline-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.field-label.compact {
  flex: 1;
  min-width: 8rem;
}
.field-label.compact input,
.field-label.compact .ap-select {
  margin-top: 0.25rem;
}
.mode-hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--muted);
  line-height: 1.4;
}
</style>
