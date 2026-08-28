<script setup lang="ts">
import { computed, ref } from "vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  busy?: boolean;
  disabled?: boolean;
  bare?: boolean;
}>();

const emit = defineEmits<{
  import: [
    payload: {
      files: File[];
      category: string;
      confirmed: boolean;
      description: string;
    },
  ];
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const category = ref("best_practices");
const confirmed = ref(true);
const description = ref("");
const dragOver = ref(false);

const categories = [
  { value: "best_practices", label: "最佳实践" },
  { value: "business_rules", label: "业务规则" },
  { value: "requirements", label: "需求补充" },
  { value: "test_cases", label: "用例参考" },
  { value: "other", label: "其他" },
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
  const input = ev.target as HTMLInputElement;
  takeFiles(input.files);
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
    category: category.value,
    confirmed: confirmed.value,
    description: description.value,
  });
}

defineExpose({ clearFiles });
</script>

<template>
  <component :is="bare ? 'div' : 'section'" :class="bare ? 'import-bare' : 'surface-card'">
    <div v-if="!bare" class="card-title-row">
      <h3>批量导入</h3>
      <span class="count-chip">{{ fileLabel }}</span>
    </div>
    <p class="hint-line">
      支持多选 TXT / MD / CSV / JSON / YAML / DOCX / PDF。一个文件可解析出多条知识；JSON/CSV
      适合大批量结构化导入。
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
      <span>可一次导入整个知识目录导出的多个文件</span>
    </div>
    <input
      ref="fileInput"
      type="file"
      class="hidden"
      multiple
      accept=".txt,.md,.csv,.json,.yaml,.yml,.docx,.pdf"
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
        <label class="field-label" style="flex: 1; min-width: 10rem; margin: 0">
          默认分类
          <ApSelect
            v-model="category"
            size="compact"
            aria-label="默认分类"
            :disabled="disabled || busy"
            :options="categories"
          />
        </label>
        <label class="check-line">
          <input v-model="confirmed" type="checkbox" :disabled="disabled || busy" />
          导入后标记为已确认
        </label>
      </div>
      <label class="field-label">
        批次备注（可选）
        <input
          v-model="description"
          :disabled="disabled || busy"
          placeholder="例如：从 TestPilot 知识库迁移 2026-07"
        />
      </label>
      <div class="inline-tools">
        <button type="button" :disabled="busy || !files.length" @click="clearFiles">清空</button>
        <span class="spacer" />
        <button
          type="button"
          class="primary"
          :disabled="disabled || busy || !files.length"
          @click="submit"
        >
          {{ busy ? "导入中…" : "开始导入" }}
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
  padding-top: 1.35rem;
}
.check-line input {
  width: auto;
  margin: 0;
}
</style>
