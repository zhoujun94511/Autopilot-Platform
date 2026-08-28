<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{
  busy?: boolean;
  disabled?: boolean;
  bare?: boolean;
}>();

const emit = defineEmits<{
  import: [payload: { files: File[] }];
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const dragOver = ref(false);

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
  emit("import", { files: [...files.value] });
}

defineExpose({ clearFiles });
</script>

<template>
  <component :is="bare ? 'div' : 'section'" :class="bare ? 'import-bare' : 'surface-card'">
    <div v-if="!bare" class="card-title-row">
      <h3>需求批量导入</h3>
      <span class="count-chip">{{ fileLabel }}</span>
    </div>
    <p class="hint-line">
      结构化入库：CSV / JSON / YAML / MD / TXT。适合从需求表、既有导出直接导入；与上方「文档→分析」互补。
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
      <strong>拖拽需求文件到此处，或点击选择</strong>
      <span>CSV 建议列：title, content, priority, req_key</span>
    </div>
    <input
      ref="fileInput"
      type="file"
      class="hidden"
      multiple
      accept=".txt,.md,.csv,.json,.yaml,.yml"
      @change="onPick"
    />

    <ul v-if="files.length" class="file-list">
      <li v-for="(f, i) in files" :key="`${f.name}-${i}`">
        <span class="name">{{ f.name }}</span>
        <span class="size">{{ Math.max(1, Math.round(f.size / 1024)) }} KB</span>
      </li>
    </ul>

    <div class="inline-tools" style="margin-top: 0.85rem">
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
  min-height: 6.5rem;
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
</style>
