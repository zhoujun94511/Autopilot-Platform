<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Requirement } from "../../api/designRequirements";
import ListPager from "./ListPager.vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  reqs: Requirement[];
  total: number;
  page: number;
  pageSize: number;
  q: string;
  priority: string;
  sourceDocumentId: string;
  sortBy: string;
  order: "asc" | "desc";
  docOptions: Array<{ id: string; filename: string }>;
  loading?: boolean;
  hasLoaded?: boolean;
  busy?: boolean;
  readonly?: boolean;
}>();

const emit = defineEmits<{
  "update:q": [v: string];
  "update:priority": [v: string];
  "update:sourceDocumentId": [v: string];
  "update:sortBy": [v: string];
  "update:order": [v: "asc" | "desc"];
  "update:page": [v: number];
  "update:pageSize": [v: number];
  edit: [item: Requirement];
  remove: [item: Requirement];
  generate: [items: Requirement[]];
  "batch-delete": [ids: string[]];
}>();

const selected = ref<Record<string, boolean>>({});

watch(
  () => props.reqs,
  (list) => {
    const next: Record<string, boolean> = {};
    for (const r of list) {
      if (selected.value[r.id]) next[r.id] = true;
    }
    selected.value = next;
  },
);

const selectedItems = computed(() => props.reqs.filter((r) => selected.value[r.id]));
const selectedIds = computed(() => selectedItems.value.map((r) => r.id));
const allChecked = computed(
  () => props.reqs.length > 0 && props.reqs.every((r) => selected.value[r.id]),
);

function toggleAll(ev: Event) {
  const on = (ev.target as HTMLInputElement).checked;
  const next: Record<string, boolean> = {};
  if (on) {
    for (const r of props.reqs) next[r.id] = true;
  }
  selected.value = next;
}

function clearSelection() {
  selected.value = {};
}

defineExpose({ clearSelection });

const priorityLabel: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  P0: "P0",
  P1: "P1",
  P2: "P2",
  P3: "P3",
};

const priorityOptions = [
  { value: "", label: "全部优先级" },
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
  { value: "P0", label: "P0" },
  { value: "P1", label: "P1" },
  { value: "P2", label: "P2" },
  { value: "P3", label: "P3" },
];
const sortOptions = [
  { value: "created_at", label: "按创建时间" },
  { value: "title", label: "按标题" },
  { value: "req_key", label: "按编号" },
];
const orderOptions = [
  { value: "desc", label: "降序" },
  { value: "asc", label: "升序" },
];
const docSelectOptions = computed(() => [
  { value: "", label: "全部来源文档" },
  ...props.docOptions.map((d) => ({ value: d.id, label: d.filename })),
]);
</script>

<template>
  <section class="surface-card">
    <div class="card-title-row">
      <h3>需求条目</h3>
      <div v-if="!readonly" class="inline-tools">
        <button
          type="button"
          class="primary"
          :disabled="busy || !selectedItems.length"
          @click="emit('generate', selectedItems)"
        >
          生成意图用例（{{ selectedItems.length }}）
        </button>
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
          placeholder="搜索编号 / 标题 / 内容…"
          @input="emit('update:q', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="priority"
        :options="priorityOptions"
        aria-label="优先级"
        @update:model-value="emit('update:priority', $event)"
      />
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="sourceDocumentId"
        :options="docSelectOptions"
        aria-label="来源文档"
        @update:model-value="emit('update:sourceDocumentId', $event)"
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

    <div v-if="hasLoaded === false || (hasLoaded !== true && loading && !reqs.length)" class="empty-state">
      <p class="empty-desc">加载中…</p>
    </div>
    <div v-else-if="!reqs.length" class="empty-state">
      <p class="empty-title">{{ total ? "无匹配需求" : "还没有需求条目" }}</p>
      <p class="empty-desc">
        {{
          total
            ? "请调整搜索或筛选条件。"
            : "用上方「导入文档」自动分析，或从 CSV/JSON 批量导入。"
        }}
      </p>
    </div>

    <div v-else class="table-wrap reqs-table">
      <table>
        <colgroup>
          <col v-if="!readonly" class="col-check" />
          <col class="col-key" />
          <col />
          <col class="col-priority" />
          <col v-if="!readonly" class="col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th v-if="!readonly">
              <input type="checkbox" :checked="allChecked" :disabled="busy" @change="toggleAll" />
            </th>
            <th>编号</th>
            <th>标题</th>
            <th>优先级</th>
            <th v-if="!readonly">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reqs" :key="r.id">
            <td v-if="!readonly">
              <input v-model="selected[r.id]" type="checkbox" :disabled="busy" />
            </td>
            <td class="mono cell-key" :title="r.req_key">{{ r.req_key }}</td>
            <td class="cell-title">
              <div class="title" :title="r.title">{{ r.title }}</div>
              <div v-if="r.content" class="excerpt" :title="r.content.length > 400 ? `${r.content.slice(0, 400)}…` : r.content">{{ r.content }}</div>
            </td>
            <td>
              <span class="pill">{{ priorityLabel[r.priority] || r.priority || "—" }}</span>
            </td>
            <td v-if="!readonly">
              <div class="row-actions">
                <button type="button" class="small" :disabled="busy" @click="emit('edit', r)">
                  编辑
                </button>
                <button
                  type="button"
                  class="small danger"
                  :disabled="busy"
                  @click="emit('remove', r)"
                >
                  删除
                </button>
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
.reqs-table {
  margin-top: 0;
}
.reqs-table table {
  table-layout: fixed;
  width: 100%;
}
.reqs-table th,
.reqs-table td {
  padding: 0.75rem 0.9rem;
  vertical-align: middle;
}
.col-check {
  width: 2.75rem;
}
.col-key {
  width: 8.5rem;
}
.col-priority {
  width: 5.5rem;
}
.col-actions {
  width: 9rem;
}
.cell-key,
.cell-title {
  min-width: 0;
}
.cell-key {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.title {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-weight: 600;
  color: var(--text);
}
.excerpt {
  margin-top: 0.22rem;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 0.75rem;
  color: var(--muted);
}
</style>
