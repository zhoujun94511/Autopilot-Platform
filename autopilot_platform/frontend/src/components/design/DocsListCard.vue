<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { DesignDocument } from "../../api/designDocs";
import ListPager from "./ListPager.vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  docs: DesignDocument[];
  total: number;
  page: number;
  pageSize: number;
  q: string;
  fileType: string;
  sortBy: string;
  order: "asc" | "desc";
  loading?: boolean;
  hasLoaded?: boolean;
  busy?: boolean;
  /** 项目只读成员：隐藏写操作 */
  readonly?: boolean;
}>();

const emit = defineEmits<{
  "update:q": [v: string];
  "update:fileType": [v: string];
  "update:sortBy": [v: string];
  "update:order": [v: "asc" | "desc"];
  "update:page": [v: number];
  "update:pageSize": [v: number];
  analyze: [doc: DesignDocument];
  reanalyze: [doc: DesignDocument];
  preview: [doc: DesignDocument];
  remove: [doc: DesignDocument];
  "batch-delete": [ids: string[]];
  "open-import": [];
}>();

const selected = ref<Record<string, boolean>>({});

watch(
  () => props.docs,
  (list) => {
    const next: Record<string, boolean> = {};
    for (const d of list) {
      if (selected.value[d.id]) next[d.id] = true;
    }
    selected.value = next;
  },
);

const selectedIds = computed(() => props.docs.filter((d) => selected.value[d.id]).map((d) => d.id));
const allChecked = computed(
  () => props.docs.length > 0 && props.docs.every((d) => selected.value[d.id]),
);

function toggleAll(ev: Event) {
  const on = (ev.target as HTMLInputElement).checked;
  const next: Record<string, boolean> = {};
  if (on) {
    for (const d of props.docs) next[d.id] = true;
  }
  selected.value = next;
}

function clearSelection() {
  selected.value = {};
}

defineExpose({ clearSelection });

function formatSize(n: number): string {
  if (!n || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const fileTypes = [
  { value: "", label: "全部类型" },
  { value: "md", label: "Markdown" },
  { value: "docx", label: "Word" },
  { value: "pdf", label: "PDF" },
  { value: "xlsx", label: "Excel" },
  { value: "csv", label: "CSV" },
  { value: "json", label: "JSON" },
  { value: "txt", label: "TXT" },
];
const sortOptions = [
  { value: "created_at", label: "按创建时间" },
  { value: "filename", label: "按文件名" },
];
const orderOptions = [
  { value: "desc", label: "降序" },
  { value: "asc", label: "升序" },
];
</script>

<template>
  <section class="surface-card">
    <div class="card-title-row">
      <h3>已上传文档</h3>
      <div v-if="!readonly" class="inline-tools">
        <button
          type="button"
          class="small danger"
          :disabled="busy || !selectedIds.length"
          @click="emit('batch-delete', selectedIds)"
        >
          批量删除（{{ selectedIds.length }}）
        </button>
      </div>
    </div>

    <div class="list-toolbar">
      <label class="toolbar-search">
        <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          :value="q"
          type="search"
          placeholder="搜索文件名 / 内容…"
          @input="emit('update:q', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="fileType"
        :options="fileTypes"
        aria-label="文件类型"
        @update:model-value="emit('update:fileType', $event)"
      />
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="sortBy"
        :options="sortOptions"
        aria-label="排序字段"
        @update:model-value="emit('update:sortBy', $event)"
      />
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="order"
        :options="orderOptions"
        aria-label="排序方向"
        @update:model-value="emit('update:order', $event as 'asc' | 'desc')"
      />
    </div>

    <div v-if="hasLoaded === false || (hasLoaded !== true && loading && !docs.length)" class="empty-state">
      <p class="empty-desc">加载中…</p>
    </div>
    <div v-else-if="!docs.length" class="empty-state">
      <p class="empty-title">{{ total ? "无匹配文档" : "还没有需求文档" }}</p>
      <p class="empty-desc">
        {{
          total
            ? "请调整搜索或筛选条件。"
            : "上传或粘贴需求，分析后可勾选生成意图用例。支持 Markdown / Word / PDF / Excel 等。"
        }}
      </p>
      <div v-if="!total && !readonly" class="empty-actions">
        <button type="button" class="primary small" @click="emit('open-import')">上传文档</button>
      </div>
    </div>

    <div v-else class="table-wrap docs-table">
      <table>
        <colgroup>
          <col v-if="!readonly" class="col-check" />
          <col class="col-file" />
          <col class="col-type" />
          <col class="col-size" />
          <col />
          <col class="col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th v-if="!readonly">
              <input type="checkbox" :checked="allChecked" :disabled="busy" @change="toggleAll" />
            </th>
            <th>文件</th>
            <th>类型</th>
            <th>大小</th>
            <th>内容预览</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in docs" :key="d.id">
            <td v-if="!readonly">
              <input v-model="selected[d.id]" type="checkbox" :disabled="busy" />
            </td>
            <td class="cell-file">
              <div class="file-name" :title="d.filename">{{ d.filename }}</div>
            </td>
            <td><span class="pill">{{ d.file_type || "—" }}</span></td>
            <td>{{ formatSize(d.size_bytes) }}</td>
            <td class="preview" :title="d.content_preview || ''">{{ d.content_preview || "—" }}</td>
            <td>
              <div class="row-actions">
                <button type="button" class="small" :disabled="busy" @click="emit('preview', d)">
                  全文预览
                </button>
                <template v-if="!readonly">
                  <button type="button" class="small primary" :disabled="busy" @click="emit('analyze', d)">
                    解析为需求
                  </button>
                  <button type="button" class="small" :disabled="busy" @click="emit('reanalyze', d)">
                    重新分析
                  </button>
                  <button type="button" class="small danger" :disabled="busy" @click="emit('remove', d)">
                    删除
                  </button>
                </template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ListPager
      :total="total"
      :page="page"
      :page-size="pageSize"
      :loading="loading"
      :disabled="busy"
      @update:page="emit('update:page', $event)"
      @update:page-size="emit('update:pageSize', $event)"
    />
  </section>
</template>

<style scoped>
.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.75rem;
  justify-content: center;
}
.docs-table {
  margin-top: 0;
}
.docs-table table {
  table-layout: fixed;
  width: 100%;
}
.docs-table th,
.docs-table td {
  padding: 0.75rem 0.9rem;
  vertical-align: middle;
}
.col-check {
  width: 2.75rem;
}
.col-file {
  width: 28%;
}
.col-type {
  width: 5.5rem;
}
.col-size {
  width: 5.5rem;
}
.col-actions {
  width: 16rem;
}
.cell-file,
.preview {
  min-width: 0;
}
.file-name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-weight: 600;
  color: var(--text);
}
.preview {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--muted);
  font-size: 0.8rem;
}
</style>
