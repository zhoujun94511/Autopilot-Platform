<script setup lang="ts">
import { computed, ref } from "vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  busy?: boolean;
  disabled?: boolean;
  /** 嵌在折叠区时去掉外层 surface-card */
  bare?: boolean;
}>();

const emit = defineEmits<{
  import: [
    payload: {
      files: File[];
      autoAnalyze: boolean;
      useLlm: boolean;
      analysisType: string;
      maxRequirements: number;
    },
  ];
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const autoAnalyze = ref(true);
const useLlm = ref(true);
const analysisType = ref("requirements");
const maxRequirements = ref(20);
const dragOver = ref(false);

const analysisTypes = [
  { value: "requirements", label: "需求条目" },
  { value: "test_points", label: "测试点" },
  { value: "business_rules", label: "业务规则" },
  { value: "comprehensive", label: "综合分析" },
];

const fileLabel = computed(() => {
  if (!files.value.length) return "未选择文件";
  if (files.value.length === 1) return files.value[0].name;
  return `已选 ${files.value.length} 个文件`;
});

function takeFiles(list: FileList | File[] | null) {
  if (!list) return;
  const next = Array.from(list).filter(Boolean);
  if (!next.length) return;
  files.value = next;
}

function onPick(ev: Event) {
  takeFiles((ev.target as HTMLInputElement).files);
}

function onDrop(ev: DragEvent) {
  ev.preventDefault();
  dragOver.value = false;
  if (props.disabled || props.busy) return;
  takeFiles(ev.dataTransfer?.files || null);
}

function clearFiles() {
  files.value = [];
  if (fileInput.value) fileInput.value.value = "";
}

function submit() {
  if (!files.value.length) return;
  emit("import", {
    files: [...files.value],
    autoAnalyze: autoAnalyze.value,
    useLlm: useLlm.value,
    analysisType: analysisType.value,
    maxRequirements: Math.max(1, Math.min(100, Number(maxRequirements.value) || 20)),
  });
}

defineExpose({ clearFiles });
</script>

<template>
  <component :is="bare ? 'div' : 'section'" :class="bare ? 'import-bare' : 'surface-card'">
    <div v-if="!bare" class="card-title-row">
      <h3>文档导入</h3>
      <span class="count-chip">{{ fileLabel }}</span>
    </div>
    <p class="hint-line">
      对齐 TestPilot：多文件上传需求原文，可选上传后自动分析入库。支持 TXT / MD / CSV / JSON /
      YAML / DOCX / PDF / XLSX。
    </p>

    <div
      class="dropzone"
      :class="{ over: dragOver, disabled: disabled || busy }"
      @dragenter.prevent="dragOver = true"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop="onDrop"
      @click="!disabled && !busy && fileInput?.click()"
    >
      <strong>拖拽文件到此处，或点击选择</strong>
      <span>可一次上传多份需求规格 / 导出文档</span>
    </div>
    <input
      ref="fileInput"
      type="file"
      class="hidden"
      multiple
      accept=".txt,.md,.csv,.json,.yaml,.yml,.docx,.pdf,.xlsx,.xls"
      @change="onPick"
    />

    <ul v-if="files.length" class="file-list">
      <li v-for="(f, i) in files" :key="`${f.name}-${i}`">
        <span class="name">{{ f.name }}</span>
        <span class="size">{{ Math.max(1, Math.round(f.size / 1024)) }} KB</span>
      </li>
    </ul>

    <div class="field-stack" style="margin-top: 0.85rem">
      <div class="inline-tools">
        <label class="check-line">
          <input v-model="autoAnalyze" type="checkbox" :disabled="disabled || busy" />
          上传后自动分析为需求
        </label>
        <label class="check-line">
          <input v-model="useLlm" type="checkbox" :disabled="disabled || busy || !autoAnalyze" />
          优先使用 AI 抽取（失败自动回退切分）
        </label>
      </div>
      <div class="inline-tools">
        <label class="field-label" style="flex: 1; min-width: 10rem; margin: 0">
          分析类型
          <ApSelect
            v-model="analysisType"
            size="compact"
            aria-label="分析类型"
            :disabled="disabled || busy || !autoAnalyze"
            :options="analysisTypes"
          />
        </label>
        <label class="field-label" style="width: 8rem; margin: 0">
          上限条数
          <input
            v-model.number="maxRequirements"
            type="number"
            min="1"
            max="100"
            :disabled="disabled || busy || !autoAnalyze"
          />
        </label>
      </div>
      <div class="inline-tools">
        <button type="button" :disabled="busy || !files.length" @click="clearFiles">清空</button>
        <span class="spacer" />
        <button
          type="button"
          class="primary"
          :disabled="disabled || busy || !files.length"
          @click="submit"
        >
          {{ busy ? "处理中…" : autoAnalyze ? "上传并分析" : "仅上传" }}
        </button>
      </div>
    </div>
  </component>
</template>

<style scoped>
.hint-line {
  margin: -0.35rem 0 0.85rem;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.45;
}
.hidden {
  display: none;
}
.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  min-height: 7.5rem;
  padding: 1rem;
  border: 1px dashed var(--line);
  border-radius: 10px;
  background: var(--surface-soft);
  cursor: pointer;
  transition: var(--transition);
  text-align: center;
}
.dropzone strong {
  color: var(--text);
  font-size: 0.92rem;
}
.dropzone span {
  color: var(--muted);
  font-size: 0.8rem;
}
.dropzone.over {
  border-color: var(--accent);
  background: var(--brand-soft);
}
.dropzone.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.file-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-height: 9rem;
  overflow: auto;
}
.file-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.4rem 0.55rem;
  border-radius: 8px;
  background: var(--chip-bg);
  border: 1px solid var(--line-soft);
  font-size: 0.8rem;
}
.file-list .name {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-list .size {
  color: var(--muted);
  flex-shrink: 0;
}
.check-line {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}
.check-line input {
  width: auto;
  margin: 0;
}
</style>
