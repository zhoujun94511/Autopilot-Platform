<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { KnowledgeItem } from "../../api/designKnowledge";
import ListPager from "./ListPager.vue";
import ApSelect from "../common/ApSelect.vue";

const props = defineProps<{
  items: KnowledgeItem[];
  total: number;
  page: number;
  pageSize: number;
  q: string;
  category: string;
  confirmed: string;
  sortBy: string;
  order: "asc" | "desc";
  loading?: boolean;
  hasLoaded?: boolean;
  busy?: boolean;
  readonly?: boolean;
}>();

const emit = defineEmits<{
  "update:q": [v: string];
  "update:category": [v: string];
  "update:confirmed": [v: string];
  "update:sortBy": [v: string];
  "update:order": [v: "asc" | "desc"];
  "update:page": [v: number];
  "update:pageSize": [v: number];
  edit: [item: KnowledgeItem];
  remove: [item: KnowledgeItem];
  "selection-change": [ids: string[]];
}>();

const selected = ref<Record<string, boolean>>({});

watch(
  () => props.items,
  (list) => {
    const next: Record<string, boolean> = {};
    for (const it of list) {
      if (selected.value[it.id]) next[it.id] = true;
    }
    selected.value = next;
  },
);

watch(
  selected,
  () => {
    const ids = props.items.filter((it) => selected.value[it.id]).map((it) => it.id);
    emit("selection-change", ids);
  },
  { deep: true },
);

const allChecked = computed(
  () => props.items.length > 0 && props.items.every((it) => selected.value[it.id]),
);

function toggleAll(ev: Event) {
  const on = (ev.target as HTMLInputElement).checked;
  const next: Record<string, boolean> = {};
  if (on) {
    for (const it of props.items) next[it.id] = true;
  }
  selected.value = next;
}

function clearSelection() {
  selected.value = {};
}

defineExpose({ clearSelection });

const categoryLabel: Record<string, string> = {
  best_practices: "最佳实践",
  business_rules: "业务规则",
  requirements: "需求补充",
  test_cases: "用例参考",
  other: "其他",
};

const categories = [
  { value: "", label: "全部分类" },
  { value: "best_practices", label: "最佳实践" },
  { value: "business_rules", label: "业务规则" },
  { value: "requirements", label: "需求补充" },
  { value: "test_cases", label: "用例参考" },
  { value: "other", label: "其他" },
];
const orderOptions = [
  { value: "desc", label: "降序" },
  { value: "asc", label: "升序" },
];
const sortOptions = [
  { value: "created_at", label: "按创建时间" },
  { value: "title", label: "按标题" },
];
const confirmedOptions = [
  { value: "", label: "全部状态" },
  { value: "true", label: "已确认" },
  { value: "false", label: "草稿" },
];
</script>

<template>
  <section class="surface-card">
    <div class="card-title-row">
      <h3>知识条目</h3>
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
          placeholder="搜索标题 / 内容…"
          @input="emit('update:q', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="category"
        :options="categories"
        aria-label="知识分类"
        @update:model-value="emit('update:category', $event)"
      />
      <ApSelect
        class="toolbar-select"
        size="toolbar"
        :model-value="confirmed"
        :options="confirmedOptions"
        aria-label="确认状态"
        @update:model-value="emit('update:confirmed', $event)"
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

    <div v-if="hasLoaded === false || (hasLoaded !== true && loading && !items.length)" class="empty-state">
      <p class="empty-desc">加载中…</p>
    </div>
    <div v-else-if="!items.length" class="empty-state">
      <p class="empty-title">{{ total ? "无匹配知识" : "知识库是空的（可选）" }}</p>
      <p class="empty-desc">
        {{
          total
            ? "请调整搜索或筛选条件。"
            : "把稳定规则、弹框处理、业务约束写进来，生成用例时可检索引用。也可先跳过，从需求文档开始。"
        }}
      </p>
    </div>

    <div v-else class="table-wrap knowledge-table">
      <table>
        <colgroup>
          <col v-if="!readonly" class="col-check" />
          <col class="col-title" />
          <col class="col-cat" />
          <col class="col-status" />
          <col />
          <col v-if="!readonly" class="col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th v-if="!readonly">
              <input type="checkbox" :checked="allChecked" :disabled="busy" @change="toggleAll" />
            </th>
            <th>标题</th>
            <th>分类</th>
            <th>状态</th>
            <th>摘要</th>
            <th v-if="!readonly">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in items" :key="it.id">
            <td v-if="!readonly">
              <input v-model="selected[it.id]" type="checkbox" :disabled="busy" />
            </td>
            <td class="cell-title">
              <div class="title" :title="it.title">{{ it.title }}</div>
            </td>
            <td>
              <span class="pill">{{ categoryLabel[it.category] || it.category }}</span>
            </td>
            <td>
              <span class="pill" :class="it.confirmed ? 'ok' : ''">
                {{ it.confirmed ? "已确认" : "草稿" }}
              </span>
            </td>
            <td class="preview" :title="it.content.length > 400 ? `${it.content.slice(0, 400)}…` : it.content">{{ it.content }}</td>
            <td v-if="!readonly">
              <div class="row-actions">
                <button type="button" class="small" :disabled="busy" @click="emit('edit', it)">
                  编辑
                </button>
                <button type="button" class="small danger" :disabled="busy" @click="emit('remove', it)">
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
.knowledge-table {
  margin-top: 0;
}
.knowledge-table table {
  table-layout: fixed;
  width: 100%;
}
.knowledge-table th,
.knowledge-table td {
  padding: 0.75rem 0.9rem;
  vertical-align: middle;
}
.col-check {
  width: 2.75rem;
}
.col-title {
  width: 26%;
}
.col-cat {
  width: 6.5rem;
}
.col-status {
  width: 5rem;
}
.col-actions {
  width: 9rem;
}
.cell-title,
.preview {
  min-width: 0;
}
.title {
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
